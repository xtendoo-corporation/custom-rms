/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Component, onMounted, onWillUnmount, useEffect, useRef, useState } from "@odoo/owl";

const WORKER_URL = "/rms_stock_count_session/static/lib/zxing-wasm/zxing_worker.js";
const RESCAN_COOLDOWN_MS = 2000;
const DETECT_INTERVAL_MS = 350;
const RETRY_MS = 4000;
const REFRESH_MS = 15000;
const SCAN_RECT = { x: 0.05, y: 0.2, w: 0.9, h: 0.6 };
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
        return true;
    } catch {
        // localStorage no disponible o lleno: el llamante puede reducir la carga.
        return false;
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
            history: [],
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
        this._cameraGeneration = 0;
        this._decoding = false;
        this._visibleCodes = new Set();
        this._snapshotsEnabled = false;
        this._worker = null;
        this._workerRequestId = 0;
        this._snapshotTasks = new Map();
        this._historyGeneration = 0;

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
        this.state.history = await this.orm.call(
            "rms.stock.count.scan", "scanner_history", [operatorState.operator.id]
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
        this._historyGeneration++;
        storageSet(this.operatorKey, null);
        clearInterval(this._refreshTimer);
        this.state.operatorState = null;
        this.state.last = null;
        this.state.history = [];
        this.state.step = "join";
        this._load();
    }

    _applyState(operatorState) {
        this.state.operatorState = operatorState;
        this._mergeHistory(operatorState.recent || []);
        if (operatorState.session.state !== "counting") {
            this.state.step = "finished";
        }
    }

    async _refresh() {
        if (this.state.step !== "scan" || this.state.pending.length || this._sending) {
            return;
        }
        const op = this.state.operatorState.operator;
        const generation = this._historyGeneration;
        const isCurrent = () => this.state.step === "scan" &&
            this.state.operatorState?.operator.id === op.id &&
            generation === this._historyGeneration;
        try {
            const operatorState = await this.orm.silent.call(
                "rms.stock.count.operator", "scanner_state", [[op.id]]
            );
            if (!isCurrent()) { return; }
            this._applyState(operatorState);
            this.state.offline = false;
        } catch {
            if (isCurrent()) { this.state.offline = true; }
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

    _onCameraCodes(codes, frame) {
        const now = Date.now();
        codes = [...new Set(codes.map((code) => (code || "").trim()).filter(Boolean))];
        const fresh = codes.filter((code) => !this._visibleCodes.has(code) &&
            now - (this._lastSeenAt[code] || 0) >= RESCAN_COOLDOWN_MS);
        this._visibleCodes = new Set(codes);
        for (const code of codes) {
            this._lastSeenAt[code] = now;
        }
        if (!fresh.length || this.state.step !== "scan") {
            return;
        }
        // Keep the entire frame: a product already visible is still essential
        // evidence for a new serial in this same batch.
        const uid = newUid();
        if (this._snapshotsEnabled) {
            try {
                this._snapshotTasks.set(uid, this._prepareSnapshot(frame));
            } catch {
                // Snapshot allocation must never discard a valid reading.
            }
        }
        this._enqueue(codes[0], { uid, codes, source: "camera" });
    }

    _prepareSnapshot(frame) {
        // Preserve this exact frame before the capture canvas is reused. JPEG
        // encoding is deferred and never holds up decoding or registration.
        const copy = document.createElement("canvas");
        const scale = Math.min(1, 1024 / Math.max(frame.width, frame.height));
        copy.width = Math.round(frame.width * scale);
        copy.height = Math.round(frame.height * scale);
        copy.getContext("2d").drawImage(frame, 0, 0, copy.width, copy.height);
        return new Promise((resolve) => {
            const encode = () => {
                try {
                    copy.toBlob((blob) => {
                        copy.width = copy.height = 0;
                        if (!blob) { resolve(null); return; }
                        const reader = new FileReader();
                        reader.onload = () => resolve(reader.result.split(",")[1]);
                        reader.onerror = () => resolve(null);
                        reader.readAsDataURL(blob);
                    }, "image/jpeg", 0.7);
                } catch {
                    copy.width = copy.height = 0;
                    resolve(null);
                }
            };
            if (window.requestIdleCallback) {
                window.requestIdleCallback(encode, { timeout: 1500 });
            } else {
                setTimeout(encode, 0);
            }
        });
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
            const saved = storageSet(
                key, this.state.pending.length ? JSON.stringify(this.state.pending) : null
            );
            if (!saved && this.state.pending.length) {
                // Prioritize durable codes if offline JPEGs exhaust localStorage.
                // Keep snapshots in memory for best-effort upload this session.
                const codesOnly = this.state.pending.map(({ snapshot, ...item }) => item);
                storageSet(key, JSON.stringify(codesOnly));
            }
        }
    }

    _enqueue(code, extra = {}) {
        code = (code || "").trim();
        if (!code || this.state.step !== "scan") {
            return;
        }
        this.state.pending.push({ uid: newUid(), code, ...extra });
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
                        "rms.stock.count.scan",
                        item.codes ? "scanner_register_batch" : "scanner_register",
                        [op.id, item.codes || item.code, item.uid],
                        item.codes ? { source: "camera" } : {}
                    );
                } catch (error) {
                    if (error && error.data && error.data.message) {
                        // Error funcional del servidor (recuento cerrado...):
                        // no tiene sentido reintentar esta lectura.
                        this.state.pending.shift();
                        this._snapshotTasks.delete(item.uid);
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
                const results = item.codes ? result : [result];
                for (const reading of results) {
                    this._applyState(reading.state);
                    this._showResult(reading, false);
                }
                const feedback = results.find((reading) => reading.status === "unknown") ||
                    results.find((reading) => reading.status === "ok") || results[results.length - 1];
                if (feedback) { this._feedback(feedback.status); }
                const first = results.find((reading) => reading.scan && reading.scan.id);
                const snapshotTask = this._snapshotTasks.get(item.uid);
                this._snapshotTasks.delete(item.uid);
                if (first && (snapshotTask || item.snapshot)) {
                    Promise.resolve(snapshotTask || item.snapshot).then((snapshot) => {
                        if (snapshot) {
                            return this.orm.silent.call("rms.stock.count.scan", "scanner_attach_snapshot",
                                [first.scan.id, snapshot]);
                        }
                    }).catch(() => {});
                }
            }
        } finally {
            this._sending = false;
        }
    }

    _mergeHistory(scans) {
        const byId = new Map(this.state.history.map((scan) => [scan.id, scan]));
        for (const scan of scans) {
            if (scan.id && scan.type !== "location") { byId.set(scan.id, scan); }
        }
        this.state.history = [...byId.values()].sort((a, b) => b.id - a.id);
    }

    _showResult(result, feedback = true) {
        const scan = result.scan || {};
        this._mergeHistory(result.scan ? [scan] : []);
        this.state.last = {
            status: result.status,
            message: result.message || scan.message || "",
            code: scan.code || "",
        };
        if (feedback) { this._feedback(result.status); }
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
        this._historyGeneration++;
        const operatorState = await this.orm.call(
            "rms.stock.count.scan", "scanner_delete", [[scanId]]
        );
        this.state.history = this.state.history.filter((scan) => scan.id !== scanId);
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

    async openReplacementLabel() {
        const op = this.state.operatorState.operator;
        const action = await this.orm.call(
            "rms.stock.count.operator", "scanner_replacement_label", [[op.id]]
        );
        await this.action.doAction(action, {
            onClose: async () => {
                const operatorState = await this.orm.call(
                    "rms.stock.count.operator", "scanner_state", [[op.id]]
                );
                this._applyState(operatorState);
            },
        });
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
    // Cámara: lector WASM local en todos los navegadores
    // ------------------------------------------------------------------

    async _startCamera() {
        this._stopCamera();
        const generation = this._cameraGeneration;
        const video = this.videoRef.el;
        if (!video) {
            return;
        }
        this.state.cameraError = null;
        try {
            await this._prepareWorker(generation);
        } catch (error) {
            if (generation === this._cameraGeneration) {
                this._stopCamera();
                this.state.cameraError = "No se pudo cargar el Worker o el lector de cámara WASM. " +
                    "Puedes seguir usando el lector PDA o escribir el código a mano.";
            }
            return;
        }
        if (generation !== this._cameraGeneration) {
            return;
        }
        try {
            const config = await this.orm.silent.call(
                "rms.stock.count.scan", "scanner_camera_config", []
            ).catch(() => ({ camera_snapshots: false }));
            if (generation !== this._cameraGeneration) {
                return;
            }
            this._snapshotsEnabled = config.camera_snapshots;
            const stream = await navigator.mediaDevices.getUserMedia({
                video: {
                    facingMode: { ideal: "environment" },
                    width: { ideal: 1920 }, height: { ideal: 1080 },
                },
                audio: false,
            });
            if (generation !== this._cameraGeneration) {
                stream.getTracks().forEach((track) => track.stop());
                return;
            }
            this._stream = stream;
            const track = stream.getVideoTracks()[0];
            try {
                if (track.getCapabilities?.().focusMode?.includes("continuous")) {
                    await track.applyConstraints({ advanced: [{ focusMode: "continuous" }] });
                }
            } catch {
                // Fixed-focus cameras and unsupported constraints are usable too.
            }
            if (generation !== this._cameraGeneration) {
                return;
            }
            video.srcObject = stream;
            await video.play();
            if (generation !== this._cameraGeneration) {
                return;
            }
            this._zxingCanvas = document.createElement("canvas");
            this._detectTimer = setInterval(
                () => this._decodeZxingFrame(video, generation), DETECT_INTERVAL_MS
            );
        } catch (error) {
            if (generation === this._cameraGeneration) {
                this._stopCamera();
                this.state.cameraError = error?.name === "NotAllowedError"
                    ? "No hay permiso para usar la cámara."
                    : `No se pudo abrir la cámara: ${error?.message || error}`;
            }
        }
    }

    _prepareWorker(generation) {
        return new Promise((resolve, reject) => {
            const worker = new Worker(WORKER_URL);
            this._worker = worker;
            const timeout = setTimeout(() => {
                worker.terminate();
                reject(new Error("Tiempo de carga agotado"));
            }, 20000);
            this._workerInitCancel = () => {
                clearTimeout(timeout);
                reject(new Error("Cámara detenida"));
            };
            worker.onerror = () => {
                clearTimeout(timeout);
                reject(new Error("Error del Worker de cámara"));
                if (generation === this._cameraGeneration) {
                    this._stopCamera();
                    this.state.cameraError = "El lector de cámara ha fallado. Puedes seguir con PDA o entrada manual.";
                }
            };
            worker.onmessage = ({ data }) => {
                if (generation !== this._cameraGeneration) { return; }
                if (data.type === "ready" || data.type === "error") {
                    clearTimeout(timeout);
                    this._workerInitCancel = null;
                    if (data.type === "error") {
                        reject(new Error(data.error));
                    } else {
                        resolve();
                    }
                    return;
                }
                if (data.id !== this._workerRequestId) { return; }
                this._decoding = false;
                if (data.error) {
                    this._stopCamera();
                    this.state.cameraError = "El lector de cámara WASM ha fallado. Puedes seguir con PDA o entrada manual.";
                    return;
                }
                if (!document.hidden) {
                    this._onCameraCodes(data.results.map((result) => result.text), this._zxingCanvas);
                }
            };
        });
    }

    _decodeZxingFrame(video, generation) {
        if (document.hidden || this._decoding || this._sending || this.state.pending.length ||
            generation !== this._cameraGeneration || !this._worker ||
            !video.videoWidth || !video.videoHeight || !this._zxingCanvas) {
            return;
        }
        this._decoding = true;
        try {
            const canvas = this._zxingCanvas;
            const cropWidth = video.videoWidth * SCAN_RECT.w;
            const cropHeight = video.videoHeight * SCAN_RECT.h;
            const scale = Math.min(1, 1280 / Math.max(cropWidth, cropHeight));
            canvas.width = Math.round(cropWidth * scale);
            canvas.height = Math.round(cropHeight * scale);
            const context = canvas.getContext("2d", { willReadFrequently: true });
            context.drawImage(video, video.videoWidth * SCAN_RECT.x,
                video.videoHeight * SCAN_RECT.y, cropWidth, cropHeight,
                0, 0, canvas.width, canvas.height);
            const imageData = context.getImageData(0, 0, canvas.width, canvas.height);
            this._worker.postMessage({ id: ++this._workerRequestId, imageData },
                [imageData.data.buffer]);
        } catch {
            this._decoding = false;
        }
    }

    _stopCamera() {
        this._cameraGeneration++;
        this._workerInitCancel?.();
        this._workerInitCancel = null;
        this._worker?.terminate();
        this._worker = null;
        this._decoding = false;
        clearInterval(this._detectTimer);
        this._detectTimer = null;
        if (this._zxingCanvas) {
            this._zxingCanvas.width = this._zxingCanvas.height = 0;
            this._zxingCanvas = null;
        }
        this._visibleCodes = new Set();
        if (this._stream) {
            this._stream.getTracks().forEach((track) => track.stop());
            this._stream = null;
        }
        if (this.videoRef.el) {
            this.videoRef.el.srcObject = null;
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
            unknown: "text-bg-warning",
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
            unknown: "Pendiente de revisar",
            ignored: "Ignorado",
        }[type] || type;
    }

    scanTypeClass(type) {
        return {
            product: "text-bg-success",
            serial: "text-bg-success",
            product_ref: "text-bg-info",
            unknown: "text-bg-warning",
            ignored: "text-bg-light border",
        }[type] || "text-bg-secondary";
    }
}

registry.category("actions").add("rms_stock_count_session.scan", StockCountScan);
