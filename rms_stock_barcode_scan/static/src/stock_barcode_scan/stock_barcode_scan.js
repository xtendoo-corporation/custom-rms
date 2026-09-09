/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadJS } from "@web/core/assets";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Component, onWillUnmount, useRef, useState } from "@odoo/owl";

const ZXING_URL = "/rms_stock_barcode_scan/static/lib/zxing/zxing.min.js";
// Cada código detectado dos veces seguidas en menos de este tiempo se
// ignora (evita que un mismo fotograma se cuente varias veces).
const RESCAN_COOLDOWN_MS = 1500;
const DETECT_INTERVAL_MS = 300;

export class StockBarcodeScan extends Component {
    static template = "rms_stock_barcode_scan.StockBarcodeScan";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.action = useService("action");
        this.videoRef = useRef("video");

        this.state = useState({
            step: "catalog", // catalog | camera | review | done
            query: "",
            products: [],
            product: null,
            locationQuery: "",
            locations: [],
            location: null,
            scans: [], // [{id, code, time}]
            cameraError: null,
            starting: false,
            confirming: false,
            result: null,
        });

        this._scannedCodes = new Set();
        this._lastScanAt = {};
        this._searchTimer = null;
        this._locationSearchTimer = null;
        this._stream = null;
        this._detectTimer = null;
        this._zxingReader = null;
        this._nextScanId = 1;

        this._loadInitial();

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
        return !!(this.state.product && this.state.location) && !this.state.starting;
    }

    async startScan() {
        if (!this.canStartScan) {
            return;
        }
        this.state.cameraError = null;
        this.state.starting = true;
        this._scannedCodes.clear();
        this._lastScanAt = {};
        this.state.scans = [];
        this.state.step = "camera";
        try {
            await this._startCamera();
        } finally {
            this.state.starting = false;
        }
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
            if (window.BarcodeDetector) {
                this._stream = await navigator.mediaDevices.getUserMedia({
                    video: { facingMode: "environment" },
                    audio: false,
                });
                video.srcObject = this._stream;
                await video.play();
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
                            this._onCodeDetected(barcode.rawValue);
                        }
                    } catch {
                        // fotograma no decodificable: se ignora, se sigue intentando
                    }
                }, DETECT_INTERVAL_MS);
            } else {
                // Safari/iOS y navegadores sin Barcode Detection API nativa:
                // se usa ZXing (librería incluida en el propio módulo) que
                // gestiona ella misma la cámara. Se usa decodeFromConstraints
                // con facingMode explícito (en vez de decodeFromVideoDevice
                // con un deviceId) porque en iOS Safari, antes de conceder
                // el permiso, enumerateDevices() devuelve dispositivos sin
                // etiquetar y a veces elige una cámara que no llega a
                // renderizar nada (pantalla en negro). No se espera (await)
                // a que la promesa termine: en modo escaneo continuo no se
                // resuelve hasta llamar a reset(), así que awaitarla dejaría
                // "starting" bloqueado para siempre; los fallos de permiso
                // se capturan igualmente con el .catch().
                await loadJS(ZXING_URL);
                const codeReader = new window.ZXing.BrowserMultiFormatReader();
                this._zxingReader = codeReader;
                const constraints = { video: { facingMode: { ideal: "environment" } }, audio: false };
                codeReader
                    .decodeFromConstraints(constraints, video, (result) => {
                        if (result) {
                            this._onCodeDetected(result.getText());
                        }
                    })
                    .catch((error) => {
                        console.error(error);
                        this.state.cameraError =
                            "No se pudo acceder a la cámara. Revisa que hayas dado permiso de " +
                            "cámara al navegador y que estés en una conexión https.";
                    });
            }
        } catch (error) {
            console.error(error);
            this.state.cameraError =
                "No se pudo acceder a la cámara. Revisa que hayas dado permiso de " +
                "cámara al navegador y que estés en una conexión https.";
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
        this.state.scans.push({ id: this._nextScanId++, code });
        this._feedback();
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
        this.stopCamera();
        this.state.step = "review";
    }

    backToCamera() {
        this.state.step = "camera";
        this.state.cameraError = null;
        this._startCamera();
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
                    this.state.scans.map((s) => s.code),
                ]
            );
            this.state.result = result;
            this.state.step = "done";
            if (result.errors.length) {
                this.notification.add(
                    `${result.applied} de ${result.total} números de serie añadidos. ` +
                    `${result.errors.length} con error.`,
                    { type: "warning" }
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

    closeAction() {
        this.action.doAction({ type: "ir.actions.act_window_close" });
    }
}

registry.category("actions").add("rms_stock_barcode_scan.scan", StockBarcodeScan);
