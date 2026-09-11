/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadJS } from "@web/core/assets";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Component, onWillUnmount, useEffect, useRef, useState } from "@odoo/owl";

const ZXING_URL = "/rms_stock_barcode_scan/static/lib/zxing/zxing.min.js";
// Cada código detectado dos veces seguidas en menos de este tiempo se
// ignora (evita que un mismo fotograma se cuente varias veces).
const RESCAN_COOLDOWN_MS = 1500;
const DETECT_INTERVAL_MS = 300;
// Zoom digital (CSS) de reserva cuando el track de cámara no soporta zoom
// nativo (p. ej. iOS Safari, o Android sin esa capability).
const CSS_ZOOM_MIN = 1;
const CSS_ZOOM_MAX = 3;
const CSS_ZOOM_STEP = 0.1;
// Tamaño mínimo (fracción del vídeo, 0-1) al que se puede reducir el
// recuadro de escaneo con el asa de redimensionar.
const MIN_SCAN_RECT_SIZE = 0.12;

export class StockBarcodeScan extends Component {
    static template = "rms_stock_barcode_scan.StockBarcodeScan";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.action = useService("action");
        this.videoRef = useRef("video");
        this.videoWrapRef = useRef("videoWrap");

        this.state = useState({
            step: "catalog", // catalog | camera | review | done
            query: "",
            products: [],
            product: null,
            locationQuery: "",
            locations: [],
            location: null,
            scans: [], // [{id, code, productStateId}]
            productStates: [], // [{id, name}]
            defaultProductStateId: false,
            cameraError: null,
            confirming: false,
            result: null,
            // Recuadro de escaneo: fracciones (0-1) del tamaño del vídeo.
            // Solo se aceptan códigos detectados dentro de este recuadro.
            scanRect: { x: 0.1, y: 0.32, w: 0.8, h: 0.36 },
            zoom: 1,
            // {min, max, step} si el track de cámara soporta zoom nativo;
            // null si hay que recurrir al zoom digital (CSS) de reserva.
            zoomCapabilities: null,
        });

        this._scannedCodes = new Set();
        this._lastScanAt = {};
        this._searchTimer = null;
        this._locationSearchTimer = null;
        this._stream = null;
        this._detectTimer = null;
        this._zxingReader = null;
        this._zxingCanvas = null;
        this._track = null;
        this._dragState = null;
        this._nextScanId = 1;

        this._loadInitial();

        // El <video t-ref="video"> solo existe en el DOM mientras
        // state.step === "camera": no se puede llamar a _startCamera()
        // justo después de asignar state.step = "camera", porque OWL
        // todavía no ha vuelto a pintar el DOM en ese momento (videoRef.el
        // seguiría siendo null). useEffect() se ejecuta DESPUÉS de que el
        // DOM se ha actualizado, así que es el sitio correcto para
        // arrancar/parar la cámara cada vez que cambia el paso.
        useEffect(
            () => {
                if (this.state.step === "camera") {
                    this._startCamera();
                    return () => this.stopCamera();
                }
            },
            () => [this.state.step]
        );

        onWillUnmount(() => this.stopCamera());
    }

    async _loadInitial() {
        const [config, products] = await Promise.all([
            this.orm.call("rms.stock.barcode.scan", "get_scan_config", []),
            this.orm.call("rms.stock.barcode.scan", "search_products", [""]),
        ]);
        if (config.location_id) {
            this.state.location = { id: config.location_id, name: config.location_name };
        }
        this.state.products = products;
        this.state.productStates = config.product_states || [];
        this.state.defaultProductStateId = config.default_product_state_id || false;
    }

    // ------------------------------------------------------------------
    // Paso 1: catálogo (producto + ubicación)
    // ------------------------------------------------------------------

    onProductQueryInput(ev) {
        this.state.query = ev.target.value;
        clearTimeout(this._searchTimer);
        this._searchTimer = setTimeout(() => this._searchProducts(), 300);
    }

    async _searchProducts() {
        this.state.products = await this.orm.call(
            "rms.stock.barcode.scan", "search_products", [this.state.query]
        );
    }

    selectProduct(product) {
        this.state.product = product;
    }

    onLocationQueryInput(ev) {
        this.state.locationQuery = ev.target.value;
        clearTimeout(this._locationSearchTimer);
        this._locationSearchTimer = setTimeout(() => this._searchLocations(), 300);
    }

    async _searchLocations() {
        this.state.locations = await this.orm.call(
            "rms.stock.barcode.scan", "search_locations", [this.state.locationQuery]
        );
    }

    selectLocation(location) {
        this.state.location = location;
        this.state.locations = [];
        this.state.locationQuery = "";
    }

    get canStartScan() {
        return !!(this.state.product && this.state.location);
    }

    startScan() {
        if (!this.canStartScan) {
            return;
        }
        this.state.cameraError = null;
        this._scannedCodes.clear();
        this._lastScanAt = {};
        this.state.scans = [];
        this.state.step = "camera";
    }

    // ------------------------------------------------------------------
    // Paso 2: cámara
    // ------------------------------------------------------------------

    async _startCamera() {
        const video = this.videoRef.el;
        if (!video) {
            return;
        }
        try {
            // La cámara se pide siempre nosotros mismos con getUserMedia
            // (facingMode explícito, nunca enumerateDevices()+deviceId: en
            // iOS Safari, antes de conceder el permiso, enumerateDevices()
            // devuelve dispositivos sin etiquetar y a veces elige una
            // cámara que no llega a renderizar nada, pantalla en negro).
            // Así el mismo track sirve tanto para la detección nativa como
            // para ZXing, y podemos aplicarle zoom nativo si lo soporta.
            this._stream = await navigator.mediaDevices.getUserMedia({
                video: { facingMode: { ideal: "environment" } },
                audio: false,
            });
            video.srcObject = this._stream;
            await video.play();
            this._track = this._stream.getVideoTracks()[0];
            this._setupZoom();

            if (window.BarcodeDetector) {
                const detector = new window.BarcodeDetector({
                    formats: [
                        "ean_13", "ean_8", "upc_a", "upc_e",
                        "code_128", "code_39", "itf", "qr_code",
                    ],
                });
                this._detectTimer = setInterval(async () => {
                    try {
                        const barcodes = await detector.detect(video);
                        for (const barcode of barcodes) {
                            if (this._isInScanRect(barcode.boundingBox, video)) {
                                this._onCodeDetected(barcode.rawValue);
                            }
                        }
                    } catch {
                        // fotograma no decodificable: se ignora, se sigue intentando
                    }
                }, DETECT_INTERVAL_MS);
            } else {
                // Safari/iOS y navegadores sin Barcode Detection API nativa:
                // se decodifica a mano con ZXing (librería incluida en el
                // propio módulo, sin llamadas a internet) solo el recorte
                // de vídeo dentro del recuadro de escaneo.
                await loadJS(ZXING_URL);
                const codeReader = new window.ZXing.BrowserMultiFormatReader();
                this._zxingReader = codeReader;
                this._zxingCanvas = document.createElement("canvas");
                this._detectTimer = setInterval(
                    () => this._decodeZxingFrame(video, codeReader),
                    DETECT_INTERVAL_MS
                );
            }
        } catch (error) {
            console.error(error);
            this.state.cameraError =
                "No se pudo acceder a la cámara. Revisa que hayas dado permiso de " +
                "cámara al navegador y que estés en una conexión https.";
        }
    }

    // Zoom nativo del track de cámara si lo soporta (Android/Chrome
    // habitualmente); si no, se recurre a un zoom digital por CSS
    // (transform: scale en el <video>, ver la plantilla).
    _setupZoom() {
        const track = this._track;
        const caps = track && track.getCapabilities ? track.getCapabilities() : null;
        if (caps && caps.zoom && caps.zoom.max > caps.zoom.min) {
            this.state.zoomCapabilities = {
                min: caps.zoom.min,
                max: caps.zoom.max,
                step: caps.zoom.step || 0.1,
            };
            const settings = track.getSettings ? track.getSettings() : {};
            this.state.zoom = settings.zoom || caps.zoom.min;
        } else {
            this.state.zoomCapabilities = null;
            this.state.zoom = 1;
        }
    }

    onZoomInput(ev) {
        const value = parseFloat(ev.target.value);
        this.state.zoom = value;
        if (this.state.zoomCapabilities && this._track && this._track.applyConstraints) {
            this._track.applyConstraints({ advanced: [{ zoom: value }] }).catch((error) => {
                console.error(error);
            });
        }
        // Sin soporte nativo: el zoom CSS se aplica solo, vía t-att-style
        // en la plantilla (transform: scale ligado a state.zoom).
    }

    get zoomMin() {
        return this.state.zoomCapabilities ? this.state.zoomCapabilities.min : CSS_ZOOM_MIN;
    }

    get zoomMax() {
        return this.state.zoomCapabilities ? this.state.zoomCapabilities.max : CSS_ZOOM_MAX;
    }

    get zoomStep() {
        return this.state.zoomCapabilities ? this.state.zoomCapabilities.step : CSS_ZOOM_STEP;
    }

    // ------------------------------------------------------------------
    // Recuadro de escaneo: arrastrar para mover, asa para redimensionar.
    // Se guarda como fracciones (0-1) del tamaño del vídeo, así que no
    // depende de la resolución real de la cámara ni de cómo se muestre.
    // ------------------------------------------------------------------

    onRectMovePointerDown(ev) {
        this._beginRectDrag(ev, "move");
    }

    onRectResizePointerDown(ev) {
        this._beginRectDrag(ev, "resize");
    }

    _beginRectDrag(ev, mode) {
        const wrap = this.videoWrapRef.el;
        if (!wrap) {
            return;
        }
        ev.preventDefault();
        const containerRect = wrap.getBoundingClientRect();
        if (!containerRect.width || !containerRect.height) {
            return;
        }
        this._dragState = {
            mode,
            pointerId: ev.pointerId,
            startClientX: ev.clientX,
            startClientY: ev.clientY,
            containerWidth: containerRect.width,
            containerHeight: containerRect.height,
            startRect: { ...this.state.scanRect },
        };
        ev.currentTarget.setPointerCapture(ev.pointerId);
    }

    onRectPointerMove(ev) {
        const drag = this._dragState;
        if (!drag || drag.pointerId !== ev.pointerId) {
            return;
        }
        const dxFrac = (ev.clientX - drag.startClientX) / drag.containerWidth;
        const dyFrac = (ev.clientY - drag.startClientY) / drag.containerHeight;
        const rect = { ...drag.startRect };
        if (drag.mode === "move") {
            rect.x = Math.min(Math.max(drag.startRect.x + dxFrac, 0), 1 - rect.w);
            rect.y = Math.min(Math.max(drag.startRect.y + dyFrac, 0), 1 - rect.h);
        } else {
            rect.w = Math.min(
                Math.max(drag.startRect.w + dxFrac, MIN_SCAN_RECT_SIZE),
                1 - rect.x
            );
            rect.h = Math.min(
                Math.max(drag.startRect.h + dyFrac, MIN_SCAN_RECT_SIZE),
                1 - rect.y
            );
        }
        this.state.scanRect = rect;
    }

    onRectPointerUp(ev) {
        if (this._dragState && this._dragState.pointerId === ev.pointerId) {
            this._dragState = null;
        }
    }

    // ¿Cae el código detectado (BarcodeDetector) dentro del recuadro?
    // boundingBox viene en píxeles nativos del vídeo (video.videoWidth/
    // videoHeight), no en píxeles de pantalla.
    _isInScanRect(boundingBox, video) {
        const vw = video.videoWidth;
        const vh = video.videoHeight;
        if (!vw || !vh) {
            return true;
        }
        const rect = this.state.scanRect;
        const rectPx = { x: rect.x * vw, y: rect.y * vh, w: rect.w * vw, h: rect.h * vh };
        const cx = boundingBox.x + boundingBox.width / 2;
        const cy = boundingBox.y + boundingBox.height / 2;
        return (
            cx >= rectPx.x && cx <= rectPx.x + rectPx.w &&
            cy >= rectPx.y && cy <= rectPx.y + rectPx.h
        );
    }

    // Fallback ZXing: recorta el fotograma actual al recuadro de escaneo
    // y decodifica solo ese recorte (HTMLCanvasElementLuminanceSource +
    // BinaryBitmap son parte de la librería vendorizada, ver
    // static/lib/zxing/zxing.min.js).
    _decodeZxingFrame(video, codeReader) {
        if (!video.videoWidth || !video.videoHeight) {
            return;
        }
        const rect = this.state.scanRect;
        const sx = Math.round(rect.x * video.videoWidth);
        const sy = Math.round(rect.y * video.videoHeight);
        const sw = Math.round(rect.w * video.videoWidth);
        const sh = Math.round(rect.h * video.videoHeight);
        if (sw <= 0 || sh <= 0) {
            return;
        }
        const canvas = this._zxingCanvas;
        canvas.width = sw;
        canvas.height = sh;
        canvas.getContext("2d").drawImage(video, sx, sy, sw, sh, 0, 0, sw, sh);
        try {
            const luminanceSource = new window.ZXing.HTMLCanvasElementLuminanceSource(canvas);
            const binaryBitmap = new window.ZXing.BinaryBitmap(
                new window.ZXing.HybridBinarizer(luminanceSource)
            );
            const result = codeReader.decodeBitmap(binaryBitmap);
            if (result) {
                this._onCodeDetected(result.getText());
            }
        } catch {
            // No se ha encontrado ningún código en este recorte: se sigue
            // intentando en el siguiente fotograma.
        }
    }

    _onCodeDetected(code) {
        code = (code || "").trim();
        if (!code) {
            return;
        }
        const now = Date.now();
        const last = this._lastScanAt[code] || 0;
        if (now - last < RESCAN_COOLDOWN_MS) {
            return;
        }
        this._lastScanAt[code] = now;
        if (this._scannedCodes.has(code)) {
            return;
        }
        this._scannedCodes.add(code);
        this.state.scans.push({
            id: this._nextScanId++,
            code,
            productStateId: this.state.defaultProductStateId,
        });
        this._feedback();
    }

    onScanStateChange(scanId, ev) {
        const scan = this.state.scans.find((s) => s.id === scanId);
        if (scan) {
            scan.productStateId = parseInt(ev.target.value, 10) || false;
        }
    }

    _feedback() {
        if (navigator.vibrate) {
            navigator.vibrate(80);
        }
        try {
            const AudioCtx = window.AudioContext || window.webkitAudioContext;
            const ctx = new AudioCtx();
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.frequency.value = 880;
            gain.gain.setValueAtTime(0.2, ctx.currentTime);
            osc.start();
            osc.stop(ctx.currentTime + 0.12);
            osc.onended = () => ctx.close();
        } catch {
            // sin audio disponible: no es crítico, se ignora
        }
    }

    removeScan(scanId) {
        const scan = this.state.scans.find((s) => s.id === scanId);
        if (scan) {
            this._scannedCodes.delete(scan.code);
        }
        this.state.scans = this.state.scans.filter((s) => s.id !== scanId);
    }

    stopCamera() {
        clearInterval(this._detectTimer);
        this._detectTimer = null;
        if (this._zxingReader) {
            this._zxingReader.reset();
            this._zxingReader = null;
        }
        this._zxingCanvas = null;
        this._track = null;
        this._dragState = null;
        if (this._stream) {
            this._stream.getTracks().forEach((track) => track.stop());
            this._stream = null;
        }
        const video = this.videoRef.el;
        if (video) {
            video.srcObject = null;
        }
    }

    finishScanning() {
        this.state.step = "review";
    }

    backToCamera() {
        this.state.cameraError = null;
        this.state.step = "camera";
    }

    // ------------------------------------------------------------------
    // Paso 3: revisar y confirmar
    // ------------------------------------------------------------------

    async confirmScan() {
        if (!this.state.scans.length || this.state.confirming) {
            return;
        }
        this.state.confirming = true;
        try {
            const result = await this.orm.call(
                "rms.stock.barcode.scan",
                "confirm_scan",
                [
                    this.state.product.id,
                    this.state.location.id,
                    this.state.scans.map((s) => ({
                        serial: s.code,
                        product_state_id: s.productStateId || false,
                    })),
                ]
            );
            this.state.result = result;
            this.state.step = "done";
            if (result.errors.length) {
                this.notification.add(
                    `${result.applied} de ${result.total} números de serie añadidos. ` +
                    `${result.errors.length} con error: ` +
                    result.errors.map((err) => `${err.serial} (${err.message})`).join("; "),
                    { type: "danger" }
                );
            } else {
                this.notification.add(
                    `${result.applied} números de serie añadidos al Inventario físico.`,
                    { type: "success" }
                );
            }
        } catch (error) {
            console.error(error);
            this.notification.add(
                "No se pudo guardar el escaneo. Inténtalo de nuevo.",
                { type: "danger" }
            );
        } finally {
            this.state.confirming = false;
        }
    }

    scanAnotherProduct() {
        this.state.step = "catalog";
        this.state.product = null;
        this.state.scans = [];
        this.state.result = null;
        this.state.query = "";
        this._searchProducts();
    }

    async closeAction() {
        // "ir.actions.act_window_close" solo cierra un diálogo modal; esta
        // pantalla se abre como una acción normal (no un modal), así que no
        // hacía nada. Se navega explícitamente a la acción estándar de
        // Inventario físico.
        try {
            await this.action.doAction("stock.quantsact", { clear_breadcrumbs: true });
        } catch (error) {
            console.error(error);
            this.notification.add(
                "No se pudo volver a Inventario físico automáticamente. " +
                "Ve a Inventario > Informes > Inventario físico.",
                { type: "warning" }
            );
        }
    }
}

registry.category("actions").add("rms_stock_barcode_scan.scan", StockBarcodeScan);
