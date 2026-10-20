/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadJS } from "@web/core/assets";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Component, onMounted, onWillUnmount, useEffect, useRef, useState } from "@odoo/owl";

// Copia de ZXing que ya trae rms_stock_barcode_scan (lectura con cámara en
// navegadores sin BarcodeDetector nativo, p. ej. Safari/iOS).
const ZXING_URL = "/rms_stock_barcode_scan/static/lib/zxing/zxing.min.js";
const RESCAN_COOLDOWN_MS = 2000;
const DETECT_INTERVAL_MS = 300;
const RETRY_MS = 4000;
const REFRESH_MS = 15000;
// Recuadro fijo (fracciones del vídeo) donde se aceptan códigos con la
// cámara: evita leer a la vez el resto de códigos de la misma etiqueta.
const SCAN_RECT = { x: 0.1, y: 0.3, w: 0.8, h: 0.4 };
const MODE_KEY = "rms_stock_count_session.inputMode";

function storageGet(key) {
    try {
        return window.localStorage.getItem(key);
    } catch {
        return null;
    }
}

function storageSet(key, value) {
    try {
        if (value === null) {
            window.localStorage.removeItem(key);
        } else {
            window.localStorage.setItem(key, value);
        }
    } catch {
        // localStorage no disponible (modo privado...): no es crítico
    }
}

function newUid() {
    if (window.crypto && window.crypto.randomUUID) {
        return window.crypto.randomUUID();
    }
    return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export class StockCountScan extends Component {
    static template = "rms_stock_count_session.StockCountScan";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.inputRef = useRef("codeInput");
        this.videoRef = useRef("video");

        const context = (this.props.action && this.props.action.context) || {};
        this.sessionId = context.active_id || false;

        this.state = useState({
            step: "loading", // loading | join | scan | finished | error
            error: null,
            session: null,
            joinName: "",
            operatorState: null,
            last: null, // {status, message}
            pending: [], // [{uid, code}] lecturas aún no confirmadas por el servidor
            offline: false,
            inputMode: storageGet(MODE_KEY) === "camera" ? "camera" : "pda",
            cameraError: null,
            panel: null, // null | "product" | "location"
            panelQuery: "",
            panelResults: [],
        });

        this._sending = false;
        this._retryTimer = null;
        this._refreshTimer = null;
        this._searchTimer = null;
        this._lastSeenAt = {};
        this._stream = null;
        this._detectTimer = null;
        this._zxingCanvas = null;

        onMounted(() => this._load());

        useEffect(
            () => {
                if (this.state.step !== "scan" || this.state.panel) {
                    return;
                }
                if (this.state.inputMode === "pda") {
                    this._focusInput();
                    return;
                }
                this._startCamera();
                return () => this._stopCamera();
            },
            () => [this.state.step, this.state.inputMode, this.state.panel]
        );

        onWillUnmount(() => {
            this._stopCamera();
            clearTimeout(this._retryTimer);
            clearInterval(this._refreshTimer);
            clearTimeout(this._searchTimer);
        });
    }

    // ------------------------------------------------------------------
    // Carga y alta del operario
    // ------------------------------------------------------------------

    get operatorKey() {
        return `rms_stock_count_session.operator.${this.sessionId}`;
    }

    get queueKey() {
        const op = this.state.operatorState && this.state.operatorState.operator;
        return op ? `rms_stock_count_session.queue.${op.id}` : null;
    }

    async _load() {
        if (!this.sessionId) {
            this.state.error = "Abre el escáner desde un recuento (botón 'Abrir escáner').";
            this.state.step = "error";
            return;
        }
        try {
            const session = await this.orm.call(
                "rms.stock.count.operator", "scanner_session_info", [this.sessionId]
            );
            this.state.session = session;
            this.state.joinName = session.default_name || "";
            const savedOperatorId = parseInt(storageGet(this.operatorKey), 10);
            const saved = session.operators.find((op) => op.id === savedOperatorId);
            if (saved && ["draft", "counting"].includes(session.state)) {
                await this.join(saved.name);
                return;
            }
            this.state.step = "join";
        } catch (error) {
            this.state.error = (error.data && error.data.message) || error.message || String(error);
            this.state.step = "error";
        }
    }

    onJoinNameInput(ev) {
        this.state.joinName = ev.target.value;
    }

    onJoinKeydown(ev) {
        if (ev.key === "Enter") {
            this.join(this.state.joinName);
        }
    }

    async join(name) {
        name = (name || "").trim();
        if (!name) {
            this.notification.add("Escribe tu nombre para empezar.", { type: "warning" });
            return;
        }
        const operatorState = await this.orm.call(
            "rms.stock.count.operator", "scanner_join", [this.sessionId, name]
        );
        this._applyState(operatorState);
        storageSet(this.operatorKey, String(operatorState.operator.id));
        this.state.pending = this._loadQueue();
        this.state.step = "scan";
        this._flushQueue();
        clearInterval(this._refreshTimer);
        this._refreshTimer = setInterval(() => this._refresh(), REFRESH_MS);
    }

    changeOperator() {
        if (this.state.pending.length) {
            this.notification.add(
                "Quedan lecturas sin enviar: espera a recuperar la conexión antes de cambiar de operario.",
                { type: "warning" }
            );
            return;
        }
        storageSet(this.operatorKey, null);
        clearInterval(this._refreshTimer);
        this.state.operatorState = null;
        this.state.last = null;
        this.state.step = "join";
        this._load();
    }

    _applyState(operatorState) {
        this.state.operatorState = operatorState;
        if (operatorState.session.state !== "counting") {
            this.state.step = "finished";
        }
    }

    async _refresh() {
        if (this.state.step !== "scan" || this.state.pending.length || this._sending) {
            return;
        }
        try {
            const op = this.state.operatorState.operator;
            const operatorState = await this.orm.silent.call(
                "rms.stock.count.operator", "scanner_state", [[op.id]]
            );
            this._applyState(operatorState);
            this.state.offline = false;
        } catch {
            this.state.offline = true;
        }
    }

    // ------------------------------------------------------------------
    // Entrada de códigos: lector PDA (modo teclado), teclado o cámara
    // ------------------------------------------------------------------

    setInputMode(mode) {
        this.state.inputMode = mode;
        storageSet(MODE_KEY, mode);
    }

    _focusInput() {
        const input = this.inputRef.el;
        if (input) {
            input.focus();
        } else {
            requestAnimationFrame(() => this._focusInput());
        }
    }

    onCodeKeydown(ev) {
        if (ev.key !== "Enter") {
            return;
        }
        ev.preventDefault();
        const code = ev.target.value;
        ev.target.value = "";
        this._enqueue(code);
    }

    addTypedCode() {
        const input = this.inputRef.el;
        if (!input) {
            return;
        }
        const code = input.value;
        input.value = "";
        this._enqueue(code);
        if (this.state.inputMode === "pda") {
            this._focusInput();
        }
    }

    // En modo PDA el lector "teclea" donde esté el foco: si se pierde (un
    // toque fuera del campo), se recupera para no perder lecturas.
    onCodeBlur() {
        if (this.state.step === "scan" && this.state.inputMode === "pda" && !this.state.panel) {
            setTimeout(() => {
                const active = document.activeElement;
                if (!active || !active.closest || !active.closest(".o_rms_cs_keep_focus")) {
                    this._focusInput();
                }
            }, 80);
        }
    }

    _onCameraCode(code) {
        code = (code || "").trim();
        if (!code) {
            return;
        }
        const now = Date.now();
        if (now - (this._lastSeenAt[code] || 0) < RESCAN_COOLDOWN_MS) {
            this._lastSeenAt[code] = now;
            return;
        }
        this._lastSeenAt[code] = now;
        this._enqueue(code);
    }

    // ------------------------------------------------------------------
    // Cola de envío: cada lectura se guarda en la PDA hasta que el
    // servidor la confirma. Si se cae la Wi-Fi se reintenta sola; el uid
    // evita que un reenvío cuente dos veces la misma lectura.
    // ------------------------------------------------------------------

    _loadQueue() {
        const key = this.queueKey;
        if (!key) {
            return [];
        }
        try {
            return JSON.parse(storageGet(key) || "[]");
        } catch {
            return [];
        }
    }

    _saveQueue() {
        const key = this.queueKey;
        if (key) {
            storageSet(key, this.state.pending.length ? JSON.stringify(this.state.pending) : null);
        }
    }

    _enqueue(code) {
        code = (code || "").trim();
        if (!code || this.state.step !== "scan") {
            return;
        }
        this.state.pending.push({ uid: newUid(), code });
        this._saveQueue();
        this._flushQueue();
    }

    async _flushQueue() {
        if (this._sending) {
            return;
        }
        this._sending = true;
        clearTimeout(this._retryTimer);
        try {
            while (this.state.pending.length && this.state.step === "scan") {
                const item = this.state.pending[0];
                const op = this.state.operatorState.operator;
                let result;
                try {
                    result = await this.orm.silent.call(
                        "rms.stock.count.scan", "scanner_register", [op.id, item.code, item.uid]
                    );
                } catch (error) {
                    if (error && error.data && error.data.message) {
                        // Error funcional del servidor (recuento cerrado...):
                        // no tiene sentido reintentar esta lectura.
                        this.state.pending.shift();
                        this._saveQueue();
                        this._showResult({ status: "error", message: error.data.message });
                        await this._refresh();
                        continue;
                    }
                    this.state.offline = true;
                    this._retryTimer = setTimeout(() => this._flushQueue(), RETRY_MS);
                    return;
                }
                this.state.offline = false;
                this.state.pending.shift();
                this._saveQueue();
                this._applyState(result.state);
                this._showResult(result);
            }
        } finally {
            this._sending = false;
        }
    }

    _showResult(result) {
        const scan = result.scan || {};
        this.state.last = {
            status: result.status,
            message: result.message || scan.message || "",
            code: scan.code || "",
        };
        this._feedback(result.status);
    }

    _feedback(status) {
        const patterns = {
            ok: { vibrate: 60, tones: [[1000, 0.1]] },
            resent: { vibrate: 0, tones: [] },
            location: { vibrate: 60, tones: [[700, 0.08], [900, 0.08]] },
            product_ref: { vibrate: 60, tones: [[700, 0.12]] },
            duplicate: { vibrate: [80, 60, 80], tones: [[400, 0.1], [400, 0.1]] },
            unknown: { vibrate: [200, 80, 200], tones: [[250, 0.35]] },
            ignored: { vibrate: 30, tones: [[500, 0.05]] },
            error: { vibrate: [200, 80, 200], tones: [[250, 0.35]] },
        };
        const pattern = patterns[status] || patterns.ok;
        if (navigator.vibrate && pattern.vibrate) {
            navigator.vibrate(pattern.vibrate);
        }
        if (!pattern.tones.length) {
            return;
        }
        try {
            const AudioCtx = window.AudioContext || window.webkitAudioContext;
            const ctx = new AudioCtx();
            let t = ctx.currentTime;
            for (const [freq, duration] of pattern.tones) {
                const osc = ctx.createOscillator();
                const gain = ctx.createGain();
                osc.connect(gain);
                gain.connect(ctx.destination);
                osc.frequency.value = freq;
                gain.gain.setValueAtTime(0.2, t);
                osc.start(t);
                osc.stop(t + duration);
                t += duration + 0.05;
            }
            setTimeout(() => ctx.close(), (t - ctx.currentTime) * 1000 + 100);
        } catch {
            // sin audio disponible: no es crítico
        }
    }

    // ------------------------------------------------------------------
    // Lecturas recientes, producto y ubicación actuales
    // ------------------------------------------------------------------

    async deleteScan(scanId) {
        const operatorState = await this.orm.call(
            "rms.stock.count.scan", "scanner_delete", [[scanId]]
        );
        if (operatorState && operatorState.operator) {
            this._applyState(operatorState);
        }
    }

    openPanel(panel) {
        this.state.panel = panel;
        this.state.panelQuery = "";
        this.state.panelResults = [];
        this._search();
    }

    closePanel() {
        this.state.panel = null;
    }

    onPanelQueryInput(ev) {
        this.state.panelQuery = ev.target.value;
        clearTimeout(this._searchTimer);
        this._searchTimer = setTimeout(() => this._search(), 300);
    }

    async _search() {
        const op = this.state.operatorState.operator;
        const method = this.state.panel === "location"
            ? "scanner_search_locations"
            : "scanner_search_products";
        this.state.panelResults = await this.orm.call(
            "rms.stock.count.operator", method, [[op.id], this.state.panelQuery]
        );
    }

    async pickPanelResult(record) {
        const op = this.state.operatorState.operator;
        const method = this.state.panel === "location" ? "scanner_set_location" : "scanner_set_product";
        const operatorState = await this.orm.call(
            "rms.stock.count.operator", method, [[op.id], record.id]
        );
        this._applyState(operatorState);
        this.state.panel = null;
    }

    async clearProduct() {
        const op = this.state.operatorState.operator;
        const operatorState = await this.orm.call(
            "rms.stock.count.operator", "scanner_set_product", [[op.id], false]
        );
        this._applyState(operatorState);
    }

    async finish() {
        if (this.state.pending.length) {
            this.notification.add(
                "Quedan lecturas sin enviar. Espera a que vuelva la conexión.",
                { type: "warning" }
            );
            return;
        }
        const op = this.state.operatorState.operator;
        await this.orm.call("rms.stock.count.operator", "scanner_finish", [[op.id]]);
        this.state.step = "finished";
    }

    async backToSession() {
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "rms.stock.count.session",
            res_id: this.sessionId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    // ------------------------------------------------------------------
    // Cámara (BarcodeDetector nativo o ZXing de reserva)
    // ------------------------------------------------------------------

    async _startCamera() {
        const video = this.videoRef.el;
        if (!video) {
            return;
        }
        this.state.cameraError = null;
        try {
            this._stream = await navigator.mediaDevices.getUserMedia({
                video: { facingMode: { ideal: "environment" } },
                audio: false,
            });
            video.srcObject = this._stream;
            await video.play();
            if (window.BarcodeDetector) {
                const detector = new window.BarcodeDetector({
                    formats: [
                        "ean_13", "ean_8", "upc_a", "upc_e", "code_128", "code_39",
                        "code_93", "itf", "codabar", "qr_code", "data_matrix",
                    ],
                });
                this._detectTimer = setInterval(async () => {
                    try {
                        const barcodes = await detector.detect(video);
                        for (const barcode of barcodes) {
                            if (this._inScanRect(barcode.boundingBox, video)) {
                                this._onCameraCode(barcode.rawValue);
                            }
                        }
                    } catch {
                        // fotograma no decodificable: se sigue intentando
                    }
                }, DETECT_INTERVAL_MS);
            } else {
                await loadJS(ZXING_URL);
                const reader = new window.ZXing.BrowserMultiFormatReader();
                this._zxingCanvas = document.createElement("canvas");
                this._detectTimer = setInterval(
                    () => this._decodeZxingFrame(video, reader), DETECT_INTERVAL_MS
                );
            }
        } catch (error) {
            this.state.cameraError =
                (error && error.name === "NotAllowedError")
                    ? "No hay permiso para usar la cámara."
                    : `No se pudo abrir la cámara: ${(error && error.message) || error}`;
        }
    }

    _inScanRect(box, video) {
        const vw = video.videoWidth;
        const vh = video.videoHeight;
        if (!vw || !vh) {
            return true;
        }
        const cx = (box.x + box.width / 2) / vw;
        const cy = (box.y + box.height / 2) / vh;
        return (
            cx >= SCAN_RECT.x && cx <= SCAN_RECT.x + SCAN_RECT.w &&
            cy >= SCAN_RECT.y && cy <= SCAN_RECT.y + SCAN_RECT.h
        );
    }

    _decodeZxingFrame(video, reader) {
        if (!video.videoWidth || !video.videoHeight || !this._zxingCanvas) {
            return;
        }
        const sx = Math.round(SCAN_RECT.x * video.videoWidth);
        const sy = Math.round(SCAN_RECT.y * video.videoHeight);
        const sw = Math.round(SCAN_RECT.w * video.videoWidth);
        const sh = Math.round(SCAN_RECT.h * video.videoHeight);
        const canvas = this._zxingCanvas;
        canvas.width = sw;
        canvas.height = sh;
        canvas.getContext("2d").drawImage(video, sx, sy, sw, sh, 0, 0, sw, sh);
        try {
            const source = new window.ZXing.HTMLCanvasElementLuminanceSource(canvas);
            const bitmap = new window.ZXing.BinaryBitmap(new window.ZXing.HybridBinarizer(source));
            const result = reader.decodeBitmap(bitmap);
            if (result) {
                this._onCameraCode(result.getText());
            }
        } catch {
            // ningún código en este recorte
        }
    }

    _stopCamera() {
        clearInterval(this._detectTimer);
        this._detectTimer = null;
        this._zxingCanvas = null;
        if (this._stream) {
            this._stream.getTracks().forEach((track) => track.stop());
            this._stream = null;
        }
    }

    // ------------------------------------------------------------------
    // Helpers de plantilla
    // ------------------------------------------------------------------

    get scanRectStyle() {
        return `left:${SCAN_RECT.x * 100}%;top:${SCAN_RECT.y * 100}%;` +
            `width:${SCAN_RECT.w * 100}%;height:${SCAN_RECT.h * 100}%;`;
    }

    get lastClass() {
        const status = this.state.last && this.state.last.status;
        return {
            ok: "text-bg-success",
            resent: "text-bg-success",
            location: "text-bg-info",
            product_ref: "text-bg-info",
            duplicate: "text-bg-warning",
            unknown: "text-bg-danger",
            ignored: "text-bg-secondary",
            error: "text-bg-danger",
            empty: "text-bg-secondary",
        }[status] || "text-bg-secondary";
    }

    scanTypeLabel(type) {
        return {
            product: "Unidad",
            serial: "Nº serie",
            product_ref: "Producto",
            unknown: "Desconocido",
            ignored: "Ignorado",
        }[type] || type;
    }

    scanTypeClass(type) {
        return {
            product: "text-bg-success",
            serial: "text-bg-success",
            product_ref: "text-bg-info",
            unknown: "text-bg-danger",
            ignored: "text-bg-light border",
        }[type] || "text-bg-secondary";
    }
}

registry.category("actions").add("rms_stock_count_session.scan", StockCountScan);
