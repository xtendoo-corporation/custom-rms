/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Component, onMounted, onWillUnmount, useEffect, useRef, useState } from "@odoo/owl";

const WORKER_URL = "/rms_stock_count_session/static/lib/zxing-wasm/zxing_worker.js";
const RESCAN_COOLDOWN_MS = 2000;
// Lector sin Enter: ráfaga de >= 4 caracteres con < 45 ms entre teclas y
// 160 ms de pausa al final = una lectura completa.
const BURST_GAP_MS = 45;
const BURST_PAUSE_MS = 160;
const BURST_MIN_CHARS = 4;
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
            verdict: null,
            missing: null,
            searchMode: false,
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
        this._selectedProductState = null;
        this._stateChangeQueue = Promise.resolve();
        this._stateChoiceGeneration = 0;

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
            clearTimeout(this._verdictTimer);
            this._audio?.close().catch(() => {});
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
        this._unlockAudio();
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
        this._selectedProductState = null;
        storageSet(this.operatorKey, null);
        clearInterval(this._refreshTimer);
        this.state.operatorState = null;
        this.state.last = null;
        this.state.history = [];
        this.state.step = "join";
        this._load();
    }

    _applyState(operatorState) {
        // An older scan/refresh response must not undo the user's newer choice.
        if (this._selectedProductState?.operatorId === operatorState.operator.id) {
            operatorState = { ...operatorState, operator: { ...operatorState.operator,
                current_state_id: this._selectedProductState.stateId } };
        }
        this.state.operatorState = operatorState;
        this.state.searchMode = Boolean(operatorState.operator.search_mode);
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
        this._unlockAudio();
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
        this._resetBurst();
        const code = ev.target.value;
        ev.target.value = "";
        this._enqueue(code);
    }

    // Lectores configurados SIN sufijo Enter (p. ej. Honeywell de fábrica):
    // el lector "teclea" el código entero en pocos milisegundos y una persona
    // no. Una ráfaga rápida seguida de una pausa se envía sola como lectura.
    onCodeInput(ev) {
        const input = ev.target;
        const now = performance.now();
        const burst = this._burst;
        if (!burst || now - burst.last > BURST_GAP_MS) {
            this._burst = { start: now, last: now, chars: 1, from: Math.max(0, input.value.length - 1) };
        } else {
            burst.last = now;
            burst.chars += 1;
        }
        clearTimeout(this._burstTimer);
        this._burstTimer = setTimeout(() => this._flushBurst(input), BURST_PAUSE_MS);
    }

    _flushBurst(input) {
        const burst = this._burst;
        this._resetBurst();
        if (!burst || !input || burst.chars < BURST_MIN_CHARS) {
            return;
        }
        if ((burst.last - burst.start) / (burst.chars - 1) > BURST_GAP_MS) {
            return;
        }
        const code = input.value.slice(burst.from);
        input.value = input.value.slice(0, burst.from);
        this._enqueue(code);
    }

    _resetBurst() {
        clearTimeout(this._burstTimer);
        this._burst = null;
    }

    addTypedCode() {
        const input = this.inputRef.el;
        if (!input) {
            return;
        }
        this._resetBurst();
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
        this.state.pending.push({ uid: newUid(), code, search_mode: this.state.searchMode,
            product_state_id: this.state.operatorState.operator.current_state_id, ...extra });
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
                        { ...(item.codes ? { source: "camera" } : {}), search_mode: Boolean(item.search_mode),
                            ...(item.product_state_id ? { product_state_id: item.product_state_id } : {}) }
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
                const results = item.codes ? (result.results || result) : [result];
                if (result.state) { this._applyState(result.state); }
                for (const reading of results) {
                    if (reading.state) { this._applyState(reading.state); }
                    this._showResult(reading, false);
                }
                const feedback = results.find((r) => r.scan?.suggestion_product_id) ||
                    results.find((r) => r.scan?.lot_name && r.sage?.v && r.sage.v !== "nos" && !["ignored", "unknown"].includes(r.status)) ||
                    results.find((r) => r.status === "duplicate") ||
                    results.find((r) => r.status === "unknown") ||
                    results.find((r) => r.status === "ok") || results[results.length - 1];
                if (feedback) {
                    this._setVerdict(this.verdictFor(feedback));
                    this._feedback(this.verdictKind(feedback), feedback.status);
                }
                const unresolvedSerials = results.filter((r) => r.status === "unknown" &&
                    r.scan?.lot_name && !r.scan?.suggestion_product_id && (!r.sage || !r.sage.n));
                if (item.codes && unresolvedSerials.length > 1) {
                    this._setVerdict({ kind: "unknown", text: "Acerca a una sola etiqueta", detail: "" });
                }
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
            if (scan.id && scan.type !== "location") {
                const previous = byId.get(scan.id) || {};
                byId.set(scan.id, { ...previous, ...scan, sage: scan.sage || previous.sage });
            }
        }
        this.state.history = [...byId.values()].sort((a, b) => b.id - a.id);
    }

    _showResult(result, feedback = true) {
        const scan = result.scan || {};
        this._mergeHistory(result.scan ? [{ ...scan, sage: result.sage || scan.sage }] : []);
        this.state.last = {
            status: result.status,
            message: result.message || scan.message || "",
            code: scan.code || "",
        };
        this._setVerdict(this.verdictFor(result));
        if (feedback) { this._feedback(this.verdictKind(result), result.status); }
    }

    _unlockAudio() {
        try {
            const AudioCtx = window.AudioContext || window.webkitAudioContext;
            if (!this._audio && AudioCtx) { this._audio = new AudioCtx(); }
            this._audio?.resume().catch(() => {});
            // A silent oscillator primes audio in the actual iOS user gesture.
            if (this._audio) {
                const osc = this._audio.createOscillator();
                const gain = this._audio.createGain();
                gain.gain.value = 0;
                osc.connect(gain); gain.connect(this._audio.destination);
                osc.start(); osc.stop(this._audio.currentTime + 0.01);
            }
        } catch { /* Audio is optional. */ }
    }

    _feedback(kind, status) {
        if (status === "resent") { return; }
        const tones = {
            here: [[1200, 0.09]], ok: [[1200, 0.09]], est: [[650, 0.1], [650, 0.1]], dep: [[650, 0.1], [650, 0.1]], twice: [[650, 0.1], [650, 0.1]], wh: [[650, 0.1], [650, 0.1]],
            co: [[650, 0.1], [650, 0.1]], dup: [[650, 0.1], [650, 0.1]],
            none: [[240, 0.35]], unknown: [[240, 0.35]],
            duplicate: [[900, 0.025]], nos: [[1000, 0.08]],
        }[kind] || [[1000, 0.08]];
        try {
            const ctx = this._audio;
            if (!ctx || ctx.state !== "running") { return; }
            let t = ctx.currentTime;
            for (const [freq, duration] of tones) {
                const osc = ctx.createOscillator();
                const gain = ctx.createGain();
                osc.connect(gain); gain.connect(ctx.destination);
                osc.frequency.value = freq;
                gain.gain.setValueAtTime(0.16, t);
                gain.gain.exponentialRampToValueAtTime(0.001, t + duration);
                osc.start(t); osc.stop(t + duration);
                t += duration + 0.07;
            }
        } catch { /* Keep counting even without audio. */ }
    }

    verdictKind(result) {
        if (result.status === "duplicate") { return "duplicate"; }
        if (result.status === "unknown" || result.scan?.type === "unknown") { return "unknown"; }
        if (result.scan?.also_in) { return "twice"; }
        return (result.sage || result.scan?.sage)?.v || "nos";
    }

    verdictFor(result) {
        const scan = result.scan || {};
        const sage = result.sage || scan.sage || {};
        const kind = this.verdictKind(result);
        const hits = (sage.h || []).slice(0, 3);
        const stateName = (value) => ({ nuevo: "Nuevo", demo: "Demo", "2mano": "2ª mano", Nuevo: "Nuevo", Demo: "Demo", "2Mano": "2ª mano" }[value] || value || "");
        const companyName = (code) => ({ "01": "RMS", "02": "Espacio", "03": "RJB" }[code] || code || "");
        const whName = (h) => (h[2] && h[2] !== h[1] ? `${h[2]} (${h[1]})` : h[1] || "");
        const hitLabel = (h) => `${h[1]} ${h[2] || ""} ${stateName(h[3])}`.trim();
        const first = hits[0] || [];
        const suggestion = scan.suggestion || result.suggestion || "";
        let text = result.message || scan.message || "";
        let detail = "";
        if (kind === "duplicate") { text = "Ya leído"; }
        else if (kind === "twice") { text = `Ya contado en ${scan.also_in}`; detail = `${scan.product_name || ""} · no lo cuentes dos veces; si está bien, Administración lo revisa`; }
        else if (kind === "unknown") { text = suggestion ? `¿Qué producto es? Sage propone: ${suggestion}` : (scan.message || result.message || "¿Qué producto es?"); }
        else if (kind === "ok") { text = `En Sage: ${companyName(first[0])} · ${whName(first)} · ${stateName(first[3])}`; detail = scan.product_name || first[4] || ""; }
        else if (kind === "est") { text = `Estado distinto: Sage dice ${stateName(first[3])}, has marcado ${sage.st || "otro"}`; detail = `${scan.product_name || first[4] || ""} · ${companyName(first[0])} · ${whName(first)}. Si es correcto, pulsa el estado y vuelve a leerlo; si no, lo revisa Administración`; }
        else if (kind === "dep") { text = "Sage lo tiene en depósito en un cliente"; detail = `${scan.product_name || first[4] || ""} · ${companyName(first[0])} · ${whName(first)} · ${stateName(first[3])}. Apártalo y avisa a Administración`; }
        else if (kind === "here") { text = `En Sage aquí (${first[2] || first[1] || "esta zona"}) · ${stateName(first[3])}`; }
        else if (kind === "wh") { text = `Sage lo tiene en ${first[2] || first[1]} · ${stateName(first[3])}`; detail = "Déjalo donde está"; }
        else if (kind === "co") { text = `Sage lo tiene en otra empresa: ${{ "01": "RMS", "02": "Espacio", "03": "RJB" }[first[0]] || first[0]}`; detail = "Déjalo donde está"; }
        else if (kind === "none") { text = "No está en Sage"; detail = this.state.operatorState?.session?.sage_mode === "global" ? "Se dará de alta en la revisión" : "Déjalo donde está"; }
        else if (kind === "dup") { text = `Duplicado en Sage: ${hits.map((h) => `${companyName(h[0])} ${hitLabel(h)}`).join(" y ")}`; detail = "Avísalo a Administración"; }
        return { kind, text, detail, scanId: scan.id, suggestionId: scan.suggestion_product_id || result.suggestion_product_id };
    }

    _setVerdict(verdict) {
        clearTimeout(this._verdictTimer);
        this.state.verdict = verdict;
        this._verdictTimer = setTimeout(() => {
            // Suggestions remain actionable without pausing the camera.
            if (!this.state.verdict?.suggestionId) { this.state.verdict = null; }
        }, 2200);
    }

    verdictIcon(kind) {
        return { here: "✓", ok: "✓", est: "⚠", dep: "⚠", twice: "⚠", wh: "⚠", co: "⚠", none: "✕", dup: "⇄", unknown: "?", duplicate: "ℹ", nos: "•" }[kind] || "•";
    }

    async useSuggestion() {
        const verdict = this.state.verdict;
        if (!verdict?.scanId || !verdict.suggestionId) { return; }
        await this.orm.call("rms.stock.count.scan", "action_use_sage_suggestion", [[verdict.scanId]]);
        this.state.verdict = null;
        this.state.history = await this.orm.call("rms.stock.count.scan", "scanner_history", [this.state.operatorState.operator.id]);
        await this._refresh();
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

    async setProductState(stateId) {
        const op = this.state.operatorState.operator;
        const generation = ++this._stateChoiceGeneration;
        this._selectedProductState = { operatorId: op.id, stateId };
        this._applyState(this.state.operatorState);
        // Keep server writes ordered even when several buttons are tapped quickly.
        const request = this._stateChangeQueue.then(() => this.orm.call(
            "rms.stock.count.operator", "scanner_set_state", [[op.id], stateId]
        ));
        this._stateChangeQueue = request.catch(() => {});
        try {
            const operatorState = await request;
            if (this.state.operatorState?.operator.id === op.id) {
                this._applyState(operatorState);
            }
        } catch {
            // Keep the explicit choice for subsequent queued readings, which carry
            // their own state; explain that the server has not saved this default.
            if (generation === this._stateChoiceGeneration) {
                this.notification.add("Estado activo en este dispositivo. No se pudo guardar en el servidor; vuelve a pulsarlo cuando haya conexión.",
                    { type: "warning" });
            }
        }
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
        action.context = { ...action.context,
            default_product_state_id: this.state.operatorState.operator.current_state_id };
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
        this.state.missing = await this.orm.call("rms.stock.count.operator", "scanner_finish", [[op.id]]);
        this.state.searchMode = false;
        this.state.step = "finished";
    }

    async startSearch() {
        const operatorState = await this.orm.call("rms.stock.count.operator", "scanner_start_search", [[this.state.operatorState.operator.id]]);
        this._applyState(operatorState);
        this.state.searchMode = true;
        this.state.step = "scan";
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
