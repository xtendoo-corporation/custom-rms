/** @odoo-module **/

import { browser } from "@web/core/browser/browser";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { ConnectionLostError, rpc } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { session } from "@web/session";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Component, onMounted, onWillUnmount, useEffect, useRef, useState } from "@odoo/owl";

const WORKER_URL = "/rms_stock_count_session/static/lib/zxing-wasm/zxing_worker.js";
const RESCAN_COOLDOWN_MS = 2000;
const PROGRESS_DEBOUNCE_MS = 700;
// Lector sin Enter: ráfaga de >= 4 caracteres tecleados a máquina (al menos
// 3 huecos rápidos, < 80 ms de media) = una lectura. Se cierra con 450 ms de
// pausa. Las pistolas Bluetooth a veces se atascan a mitad de código (se
// midieron pausas de 100-150 ms, sobre todo tras el primer carácter): hasta
// 3 pausas de hasta 400 ms dentro de un código NO lo parten. Partir un nº de
// serie es peor que fundir dos lecturas: lo fundido se ve como sobrante; lo
// partido se guardaba como un nº de serie falso y dejaba restos en la casilla.
const BURST_GAP_MS = 80;
const BURST_JOIN_MS = 90;
const BURST_STALL_MS = 400;
const BURST_MAX_STALLS = 3;
const BURST_PAUSE_MS = 450;
const BURST_MIN_CHARS = 4;
const DETECT_INTERVAL_MS = 350;
// Reintentos de la cola con espera creciente mientras haya pendientes.
const RETRY_STEPS_MS = [2000, 4000, 8000, 16000, 30000];
// Una llamada que no contesta en este tiempo se da por fallida y se reintenta
// (el navegador no avisa de un corte "por tiempo agotado").
const SEND_TIMEOUT_MS = 25000;
// Errores internos del servidor seguidos para UNA lectura antes de apartarla.
const MAX_SERVER_TRIES = 5;
const STUCK_INPUT_MS = 1000;
const SLOW_QUEUE_MS = 1500;
// Errores del propio programa (validación): reintentar no cambia nada.
const USER_ERRORS = new Set([
    "odoo.exceptions.UserError", "odoo.exceptions.ValidationError", "odoo.exceptions.AccessError",
    "odoo.exceptions.MissingError", "odoo.exceptions.AccessDenied", "odoo.exceptions.RedirectWarning",
]);
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
        this.dialog = useService("dialog");
        this.listRef = useRef("readingsScroll");
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
            pending: [], // [{uid, code, at, tries}] lecturas aún no confirmadas por el servidor
            failed: [], // [{uid, code, error}] lecturas que el servidor rechaza: a revisar
            conn: "ok", // ok | offline | server | expired
            queueSlow: false, // hay pendientes desde hace más de SLOW_QUEUE_MS
            sendingUid: null,
            stuck: false, // texto sin procesar en la casilla de lectura
            audioLocked: false,
            dupId: null, // lectura repetida: se resalta "Ya leído" y sube arriba
            inputMode: storageGet(MODE_KEY) === "camera" ? "camera" : "pda",
            cameraError: null,
            panel: null, // null | "product" | "location" | "sage" | "qty"
            panelQuery: "",
            panelResults: [],
            progress: null, // marcador: {site, has_sage, counted, pending, not_in_sage, review}
            expandedId: null, // lectura desplegada en la lista compacta
            sagePick: null, // fila de "Buscar en Sage" elegida (mesa sin pegatina)
            sagePickStateId: null,
            // "Por cantidad": artículo sin nº de serie elegido y lo tecleado.
            qtyPick: null,
            qtyValue: "",
            qtyStateId: null,
            qtyConfirm: null, // {existing, by}: ya hay cantidad apuntada, ¿sumar o sustituir?
            qtyEditScanId: null, // corrigiendo la cantidad de una lectura ya hecha
            qtyBusy: false,
            qtyDone: null, // último apunte guardado (aviso verde)
        });
        this.qtyPanelRef = useRef("qtyPanel");
        this.qtyKeys = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "C", "0", "back"];

        this._sending = false;
        this._retryTimer = null;
        this._retryStep = 0;
        this._gone = new Set(); // uids ya guardados o descartados en esta pestaña
        this._activeXhr = null;
        this._allowUnload = false;
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

        // Pistola lista desde el primer momento: si el foco no está en un campo
        // de texto (se tocó una línea, un botón...), lo que "teclee" la pistola
        // se lleva a la casilla de lectura en vez de perderse.
        this._onGlobalKeydown = (ev) => this._redirectScannerKey(ev);
        // La cola se reintenta sola al volver la red, el foco o la pestaña.
        this._onWake = () => {
            if (!document.hidden) { this._retryNow(false); }
        };
        this._onOffline = () => {
            if (this.state.step === "scan") { this.state.conn = "offline"; }
        };
        this._onStorage = (ev) => {
            if (ev.key && ev.key === this.queueKey && this.state.step === "scan") {
                this._adoptStored();
                this._flushQueue();
            }
        };
        this._onBeforeUnload = (ev) => {
            if (!this._allowUnload && (this.state.pending.length || this.state.failed.length)) {
                ev.preventDefault();
                ev.returnValue = "Hay lecturas sin enviar.";
                return ev.returnValue;
            }
        };
        // El navegador no deja sonar nada hasta el primer toque o tecla.
        this._onGesture = () => {
            if (this.state.audioLocked) { this._unlockAudio(); }
        };
        onMounted(() => {
            window.addEventListener("keydown", this._onGlobalKeydown, true);
            window.addEventListener("online", this._onWake);
            window.addEventListener("offline", this._onOffline);
            window.addEventListener("focus", this._onWake);
            document.addEventListener("visibilitychange", this._onWake);
            window.addEventListener("storage", this._onStorage);
            window.addEventListener("beforeunload", this._onBeforeUnload);
            for (const name of ["pointerdown", "touchend", "keydown"]) {
                window.addEventListener(name, this._onGesture, true);
            }
            this._load();
        });

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
            window.removeEventListener("keydown", this._onGlobalKeydown, true);
            window.removeEventListener("online", this._onWake);
            window.removeEventListener("offline", this._onOffline);
            window.removeEventListener("focus", this._onWake);
            document.removeEventListener("visibilitychange", this._onWake);
            window.removeEventListener("storage", this._onStorage);
            window.removeEventListener("beforeunload", this._onBeforeUnload);
            for (const name of ["pointerdown", "touchend", "keydown"]) {
                window.removeEventListener(name, this._onGesture, true);
            }
            this._destroyed = true;
            this._stopCamera();
            clearTimeout(this._retryTimer);
            clearTimeout(this._slowTimer);
            clearTimeout(this._stuckTimer);
            clearTimeout(this._burstTimer);
            clearInterval(this._refreshTimer);
            clearTimeout(this._searchTimer);
            clearTimeout(this._verdictTimer);
            clearTimeout(this._progressTimer);
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

    get failedKey() {
        const op = this.state.operatorState && this.state.operatorState.operator;
        return op ? `rms_stock_count_session.failed.${op.id}` : null;
    }

    // Llamada al servidor que SIEMPRE termina: el rpc de Odoo no resuelve ni
    // rechaza cuando el navegador corta por tiempo agotado (evento "timeout"),
    // y la cola se quedaba esperando para siempre.
    _send(model, method, args, kwargs = {}) {
        const url = `/web/dataset/call_kw/${model}/${method}`;
        const xhr = new browser.XMLHttpRequest();
        const promise = new Promise((resolve, reject) => {
            const lost = () => reject(new ConnectionLostError(url));
            xhr.addEventListener("timeout", lost);
            xhr.addEventListener("abort", lost);
            const request = rpc(url, { model, method, args, kwargs: { ...kwargs, context: { ...user.context } } },
                { silent: true, xhr });
            try {
                xhr.timeout = SEND_TIMEOUT_MS;
            } catch { /* sin límite propio: queda el del navegador */ }
            request.then(resolve, (error) => {
                try {
                    error.httpStatus = xhr.status;
                    error.responseURL = xhr.responseURL || "";
                } catch { /* error no ampliable */ }
                reject(error);
            });
        });
        promise.xhr = xhr;
        return promise;
    }

    // Qué ha fallado: "expired" (sesión caducada), "network" (sin red o
    // servidor caído: reintentar siempre), "server" (error interno: reintentar
    // unas cuantas veces) o "user" (el programa rechaza la lectura: mostrar).
    async _errorKind(error) {
        const name = error && (error.exceptionName || (error.data && error.data.name)) || "";
        if (error && error.name === "RPC_ERROR") {
            if (error.code === 100 || /SessionExpired/.test(name)) { return "expired"; }
            return USER_ERRORS.has(name) ? "user" : "server";
        }
        if (error && /\/web\/login/.test(error.responseURL || "")) { return "expired"; }
        if (error && error.httpStatus === 404) {
            // Sin sesión Odoo no sabe qué base es y contesta 404 a las llamadas;
            // si el servidor sí responde a una consulta pública, es la sesión.
            return (await this._serverAlive()) ? "expired" : "network";
        }
        return "network";
    }

    async _serverAlive() {
        try {
            const response = await browser.fetch("/web/webclient/version_info", {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ jsonrpc: "2.0", method: "call", params: {} }),
            });
            return response.ok && Boolean((await response.json()).result);
        } catch {
            return false;
        }
    }

    _errorText(error, kind) {
        const detail = (error && error.data && error.data.message) || "";
        if (kind === "user") {
            return detail || "El programa no admite esta lectura.";
        }
        return "El servidor ha dado un error al guardar esta lectura. Pulsa Reintentar; " +
            "si sigue igual, avisa al responsable.";
    }

    // Enlace para volver a entrar SIEMPRE en la misma base de datos y al escáner.
    get loginUrl() {
        const here = window.location.pathname + window.location.search + window.location.hash;
        return `/web/login?db=${encodeURIComponent(session.db || "")}&redirect=${encodeURIComponent(here)}`;
    }

    onLoginClick() {
        // Las lecturas pendientes están guardadas en el dispositivo: sin aviso de salida.
        this._allowUnload = true;
    }

    // Indicador fijo de la barra: dónde están ahora mismo las lecturas.
    get saveStatus() {
        const pending = this.state.pending.length;
        const failed = this.state.failed.length;
        const tail = pending ? ` · ${pending} pendiente${pending === 1 ? "" : "s"}` : "";
        if (this.state.conn === "expired") {
            return { kind: "bad", icon: "fa-lock", text: `Sesión caducada${tail}`, retry: false };
        }
        if (this.state.conn === "offline") {
            return { kind: "bad", icon: "fa-exclamation-triangle", text: `Sin conexión${tail}`, retry: true };
        }
        if (pending && (this.state.queueSlow || this.state.conn === "server")) {
            return { kind: "warn", icon: "fa-clock-o", retry: true,
                text: `${pending} pendiente${pending === 1 ? "" : "s"} de enviar` };
        }
        if (this.state.conn === "server") {
            return { kind: "warn", icon: "fa-exclamation-triangle", text: "El servidor da errores", retry: true };
        }
        if (failed) {
            return { kind: "bad", icon: "fa-exclamation-circle", text: `${failed} con error: revisar`, retry: false };
        }
        if (pending) {
            return { kind: "busy", icon: "fa-cloud-upload", text: `Guardando ${pending}…`, retry: false };
        }
        return { kind: "ok", icon: "fa-check-circle", text: "Todo guardado", retry: false };
    }

    // Filas de la lista: la lectura repetida ("Ya leído") sube arriba.
    get visibleRows() {
        const rows = this.state.history.filter((scan) => scan.type !== "product_ref");
        const index = this.state.dupId ? rows.findIndex((scan) => scan.id === this.state.dupId) : -1;
        if (index > 0) {
            rows.unshift(...rows.splice(index, 1));
        }
        return rows;
    }

    get pendingRows() {
        return [...this.state.pending].reverse();
    }

    itemCode(item) {
        return item.codes && item.codes.length > 1 ? `${item.code} (+${item.codes.length - 1})` : item.code;
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
        this._gone = new Set();
        this.state.pending = this._readStored(this.queueKey);
        this.state.failed = this._readStored(this.failedKey);
        this.state.conn = "ok";
        this.state.dupId = null;
        this.state.step = "scan";
        this._retryStep = 0;
        this._touchQueueClock();
        this._flushQueue();
        this._scheduleProgress(0);
        clearInterval(this._refreshTimer);
        this._refreshTimer = setInterval(() => this._refresh(), REFRESH_MS);
    }

    // Marcador de avance: se pide al servidor con un pequeño retraso para
    // agrupar las lecturas seguidas de la pistola en una sola consulta.
    _scheduleProgress(delay = PROGRESS_DEBOUNCE_MS) {
        clearTimeout(this._progressTimer);
        this._progressTimer = setTimeout(() => this._loadProgress(), delay);
    }

    async _loadProgress() {
        const op = this.state.operatorState?.operator;
        if (!op || this.state.step !== "scan") {
            return;
        }
        try {
            const progress = await this._send(
                "rms.stock.count.operator", "scanner_progress", [[op.id]]
            );
            if (this.state.operatorState?.operator.id === op.id) {
                this.state.progress = progress;
            }
        } catch {
            // El marcador es informativo: sin conexión se queda el último valor.
        }
    }

    // Con lecturas sin enviar o con error no se sale: se quedarían sin guardar.
    _blockedByQueue(action) {
        if (this.state.pending.length) {
            this.notification.add(
                `Quedan lecturas sin enviar: espera a que se envíen antes de ${action}.`, { type: "warning" });
            return true;
        }
        if (this.state.failed.length) {
            this.notification.add(
                `Hay lecturas con error sin revisar: reinténtalas o descártalas antes de ${action}.`,
                { type: "warning" });
            return true;
        }
        return false;
    }

    changeOperator() {
        if (this._blockedByQueue("cambiar de operario")) {
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
            const operatorState = await this._send(
                "rms.stock.count.operator", "scanner_state", [[op.id]]
            );
            if (!isCurrent()) { return; }
            this._applyState(operatorState);
            this.state.conn = "ok";
            // Otros operarios también cuentan: el marcador se pone al día.
            this._scheduleProgress(0);
        } catch (error) {
            const kind = await this._errorKind(error);
            if (isCurrent() && kind !== "user") {
                this.state.conn = kind === "expired" ? "expired" : kind === "server" ? "server" : "offline";
            }
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

    _redirectScannerKey(ev) {
        if (this.state.step !== "scan" || this.state.inputMode !== "pda" || this.state.panel) {
            return;
        }
        if (ev.ctrlKey || ev.metaKey || ev.altKey || ev.isComposing) {
            return;
        }
        const input = this.inputRef.el;
        const target = ev.target;
        if (!input || target === input) {
            return;
        }
        // Escribiendo en otro campo (nombre, buscadores) o con un diálogo abierto
        // (asistente de etiqueta): no se toca.
        if (target && target.closest && (target.closest("input, textarea, [contenteditable='true'], .modal"))) {
            return;
        }
        if (document.querySelector(".modal.show, .o_dialog")) {
            return;
        }
        if (ev.key === "Enter" || ev.key === "Tab") {
            if (input.value) {
                ev.preventDefault();
                ev.stopPropagation();
                this._submitInput(input);
            }
            return;
        }
        if (ev.key.length !== 1) {
            return;
        }
        ev.preventDefault();
        ev.stopPropagation();
        input.focus();
        input.value += ev.key;
        this.onCodeInput({ target: input, timeStamp: ev.timeStamp });
    }

    // Terminador del lector (Enter o Tab) o botón Añadir: todo lo que hay en
    // la casilla es una lectura.
    _submitInput(input) {
        this._resetBurst();
        const code = input.value;
        input.value = "";
        this._watchInput(input);
        this._enqueue(code);
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
        // Enter siempre; Tab solo si hay algo leído (sin texto, Tab navega).
        if (ev.key !== "Enter" && !(ev.key === "Tab" && ev.target.value && !ev.shiftKey)) {
            return;
        }
        ev.preventDefault();
        this._submitInput(ev.target);
    }

    // Lectores configurados SIN sufijo Enter (p. ej. Honeywell de fábrica):
    // el lector "teclea" el código entero en pocos milisegundos y una persona
    // no. Una ráfaga rápida seguida de una pausa se envía sola como lectura.
    onCodeInput(ev) {
        const input = ev.target;
        if (ev.inputType && ev.inputType.startsWith("delete")) {
            this._resetBurst();
            this._watchInput(input);
            return;
        }
        // Hora de la tecla, no la de proceso: con la pantalla ocupada los
        // eventos llegan a trompicones y dos lecturas parecerían una sola.
        const now = ev.timeStamp || performance.now();
        const burst = this._burst;
        const gap = burst ? now - burst.last : Infinity;
        if (burst && gap <= BURST_JOIN_MS) {
            burst.fast += 1;
            burst.fastTime += Math.max(0, gap);
            burst.last = now;
            burst.chars += 1;
        } else if (burst && gap <= BURST_STALL_MS && burst.stalls < BURST_MAX_STALLS) {
            // Tropiezo de la pistola a mitad de código: sigue siendo la misma lectura.
            burst.stalls += 1;
            burst.last = now;
            burst.chars += 1;
        } else {
            let from = Math.max(0, input.value.length - 1);
            if (burst && this._isScannerBurst(burst) && burst.from < from) {
                // Empieza otra lectura sin que la anterior llegara a su pausa
                // (doble gatillo, dos códigos en la misma etiqueta): la
                // anterior está completa y se envía ya; no se funden.
                const code = input.value.slice(burst.from, from);
                input.value = input.value.slice(0, burst.from) + input.value.slice(from);
                from = burst.from;
                this._burst = null;
                this._enqueue(code);
            }
            this._burst = { last: now, chars: 1, from, fast: 0, fastTime: 0, stalls: 0 };
        }
        clearTimeout(this._burstTimer);
        this._burstTimer = setTimeout(() => this._flushBurst(input), BURST_PAUSE_MS);
        this._watchInput(input);
    }

    _isScannerBurst(burst) {
        return burst.chars >= BURST_MIN_CHARS && burst.fast >= BURST_MIN_CHARS - 1 &&
            burst.fastTime / burst.fast <= BURST_GAP_MS;
    }

    _flushBurst(input) {
        const burst = this._burst;
        this._resetBurst();
        if (!burst || !input || !this._isScannerBurst(burst)) {
            this._watchInput(input);
            return;
        }
        const code = input.value.slice(burst.from);
        input.value = input.value.slice(0, burst.from);
        this._watchInput(input);
        this._enqueue(code);
    }

    // Nunca texto pegado en la casilla sin enviar ni avisar: si queda algo
    // sin procesar más de 1 s, se avisa en ámbar.
    _watchInput(input) {
        clearTimeout(this._stuckTimer);
        if (!input || !input.value) {
            this.state.stuck = false;
            return;
        }
        this._stuckTimer = setTimeout(() => {
            const el = this.inputRef.el;
            this.state.stuck = Boolean(el && el.value && !this._burst);
            if (el && el.value && this._burst) { this._watchInput(el); }
        }, STUCK_INPUT_MS);
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
        this._submitInput(input);
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

    _readStored(key) {
        if (!key) {
            return [];
        }
        try {
            const items = JSON.parse(storageGet(key) || "[]");
            return Array.isArray(items) ? items.filter((item) => item && item.uid && item.code) : [];
        } catch {
            return [];
        }
    }

    // Lecturas que otra pestaña del mismo operario dejó en la cola del
    // dispositivo: se adoptan (el servidor no las duplica: mismo client_uid).
    _adoptStored() {
        const known = new Set([...this.state.pending, ...this.state.failed].map((item) => item.uid));
        const foreign = this._readStored(this.queueKey).filter(
            (item) => !known.has(item.uid) && !this._gone.has(item.uid));
        if (foreign.length) {
            this.state.pending.push(...foreign);
            this.state.pending.sort((a, b) => (a.at || 0) - (b.at || 0));
            this._touchQueueClock();
        }
    }

    _saveQueue() {
        this._adoptStored();
        this._store(this.queueKey, this.state.pending);
        this._store(this.failedKey, this.state.failed);
    }

    _store(key, items) {
        if (!key) {
            return;
        }
        const saved = storageSet(key, items.length ? JSON.stringify(items) : null);
        if (!saved && items.length) {
            // Prioritize durable codes if offline JPEGs exhaust localStorage.
            // Keep snapshots in memory for best-effort upload this session.
            const codesOnly = items.map(({ snapshot, ...item }) => item);
            storageSet(key, JSON.stringify(codesOnly));
        }
    }

    _enqueue(code, extra = {}) {
        code = (code || "").trim();
        if (!code || this.state.step !== "scan") {
            return;
        }
        this.state.pending.push({ uid: newUid(), code, at: Date.now(), search_mode: this.state.searchMode,
            product_state_id: this.state.operatorState.operator.current_state_id, ...extra });
        this._saveQueue();
        this._touchQueueClock();
        // Con el servidor dando errores se respeta la espera: cada lectura
        // nueva no debe gastar un intento de la que está a la cabeza.
        if (!(this._retryTimer && this.state.conn === "server")) {
            this._flushQueue();
        }
    }

    _dropPending(uid) {
        const index = this.state.pending.findIndex((item) => item.uid === uid);
        if (index >= 0) {
            this.state.pending.splice(index, 1);
        }
    }

    // "N pendientes" solo se pinta en ámbar si llevan un rato sin entrar: en
    // marcha normal cada lectura está pendiente unas décimas.
    _touchQueueClock() {
        if (!this.state.pending.length) {
            clearTimeout(this._slowTimer);
            this._slowTimer = null;
            this.state.queueSlow = false;
        } else if (!this._slowTimer && !this.state.queueSlow) {
            this._slowTimer = setTimeout(() => {
                this._slowTimer = null;
                this.state.queueSlow = this.state.pending.length > 0;
            }, SLOW_QUEUE_MS);
        }
    }

    _scheduleRetry() {
        clearTimeout(this._retryTimer);
        const delay = RETRY_STEPS_MS[Math.min(this._retryStep, RETRY_STEPS_MS.length - 1)];
        this._retryStep += 1;
        this._retryTimer = setTimeout(() => this._flushQueue(), delay);
    }

    // Botón "Reintentar ahora", vuelta de la red o de la pestaña.
    _retryNow(byUser = true) {
        if (this.state.step !== "scan") {
            return;
        }
        this._retryStep = 0;
        if (!this.state.pending.length) {
            if (this.state.conn !== "ok") { this._refresh(); }
        } else if (!this._sending) {
            this._flushQueue();
        } else if (byUser && this._activeXhr && Date.now() - this._sendStarted > 3000) {
            // Envío colgado: se corta y se manda otra vez (el servidor no duplica).
            this._resendAfterAbort = true;
            this._activeXhr.abort();
        }
        if (byUser && this.state.inputMode === "pda") {
            this._focusInput();
        }
    }

    retryNow() {
        this._retryNow(true);
    }

    // Lectura que el servidor rechaza: se aparta a "Lecturas con error" (a la
    // vista, con Reintentar/Descartar) y la cola sigue con las demás.
    _setAside(item, message) {
        this._dropPending(item.uid);
        const { tries, ...rest } = item;
        this.state.failed.push({ ...rest, error: message });
        this._snapshotTasks.delete(item.uid);
        this._saveQueue();
        this._touchQueueClock();
        this.state.last = { status: "error", message, code: item.code };
        this._feedback("none", "error");
    }

    retryFailed(uid) {
        const index = this.state.failed.findIndex((item) => item.uid === uid);
        if (index < 0) {
            return;
        }
        const [{ error, ...item }] = this.state.failed.splice(index, 1);
        this.state.pending.push({ ...item, tries: 0 });
        this._saveQueue();
        this._touchQueueClock();
        this._retryStep = 0;
        this._flushQueue();
        if (this.state.inputMode === "pda") { this._focusInput(); }
    }

    retryAllFailed() {
        for (const item of [...this.state.failed]) {
            this.retryFailed(item.uid);
        }
    }

    discardFailed(uid) {
        const item = this.state.failed.find((failed) => failed.uid === uid);
        if (!item) {
            return;
        }
        this.dialog.add(ConfirmationDialog, {
            title: "Descartar lectura",
            body: `¿Descartar la lectura «${this.itemCode(item)}»? No se guardará en el recuento.`,
            confirmLabel: "Descartar",
            cancelLabel: "Cancelar",
            confirm: () => {
                const index = this.state.failed.findIndex((failed) => failed.uid === uid);
                if (index >= 0) {
                    this.state.failed.splice(index, 1);
                    this._gone.add(uid);
                    this._saveQueue();
                }
            },
            cancel: () => {},
        }, { onClose: () => { if (this.state.inputMode === "pda") { this._focusInput(); } } });
    }

    async _flushQueue() {
        if (this._sending) {
            return;
        }
        this._sending = true;
        clearTimeout(this._retryTimer);
        this._retryTimer = null;
        try {
            while (this.state.pending.length && this.state.step === "scan" && !this._destroyed) {
                const item = this.state.pending[0];
                const op = this.state.operatorState.operator;
                let result;
                try {
                    this.state.sendingUid = item.uid;
                    const request = this._send(
                        "rms.stock.count.scan",
                        item.codes ? "scanner_register_batch" : "scanner_register",
                        [op.id, item.codes || item.code, item.uid],
                        { ...(item.codes ? { source: "camera" } : {}), search_mode: Boolean(item.search_mode),
                            ...(item.product_state_id ? { product_state_id: item.product_state_id } : {}) }
                    );
                    this._activeXhr = request.xhr;
                    this._sendStarted = Date.now();
                    result = await request;
                } catch (error) {
                    this._activeXhr = null;
                    this.state.sendingUid = null;
                    if (this._resendAfterAbort) {
                        this._resendAfterAbort = false;
                        continue;
                    }
                    const kind = await this._errorKind(error);
                    if (this._destroyed) {
                        return;
                    }
                    if (kind === "user") {
                        // El programa rechaza ESTA lectura (recuento cerrado...):
                        // reintentar en bucle no sirve; se enseña y sigue la cola.
                        this._setAside(item, this._errorText(error, kind));
                        continue;
                    }
                    if (kind === "server") {
                        item.tries = (item.tries || 0) + 1;
                        if (item.tries > MAX_SERVER_TRIES) {
                            this._setAside(item, this._errorText(error, kind));
                            continue;
                        }
                        this._saveQueue();
                    }
                    // Sin red, servidor caído, error interno o sesión caducada:
                    // la lectura se queda en la cola y se reintenta sola.
                    this.state.conn = kind === "expired" ? "expired" : kind === "server" ? "server" : "offline";
                    this._scheduleRetry();
                    return;
                }
                this._activeXhr = null;
                this._resendAfterAbort = false;
                this.state.sendingUid = null;
                this.state.conn = "ok";
                this._retryStep = 0;
                this._gone.add(item.uid);
                this._dropPending(item.uid);
                this._saveQueue();
                this._touchQueueClock();
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
                // Lectura repetida: "Ya leído" sobre su fila, que sube arriba.
                const repeated = results.find((r) => r.status === "duplicate" && r.scan?.id);
                this.state.dupId = repeated ? repeated.scan.id : null;
                if (repeated && this.listRef.el) {
                    this.listRef.el.scrollTop = 0;
                }
                const unresolvedSerials = results.filter((r) => r.status === "unknown" &&
                    r.scan?.lot_name && !r.scan?.suggestion_product_id && (!r.sage || !r.sage.n));
                if (item.codes && unresolvedSerials.length > 1) {
                    this._setVerdict({ kind: "unknown", text: "Acerca a una sola etiqueta", detail: "" });
                }
                this._scheduleProgress();
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
            this.state.sendingUid = null;
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
            if (!this._audio && AudioCtx) {
                this._audio = new AudioCtx();
                this._audio.onstatechange = () => this._checkAudio();
            }
            this._audio?.resume().then(() => this._checkAudio()).catch(() => {});
            // Tras recargar no ha habido ningún toque: el navegador deja el
            // sonido bloqueado y se avisa hasta el primer toque o tecla.
            setTimeout(() => this._checkAudio(), 400);
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

    _checkAudio() {
        if (!this._destroyed) {
            this.state.audioLocked = Boolean(this._audio && this._audio.state !== "running");
        }
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
        else if (kind === "wh") {
            const global = this.state.operatorState?.session?.sage_mode === "global";
            text = global ? `Sage lo tiene en otra nave: ${companyName(first[0])} · ${whName(first)} · ${stateName(first[3])}`
                : `Sage lo tiene en ${first[2] || first[1]} · ${stateName(first[3])}`;
            detail = global ? "Cuéntalo aquí: queda en la lista de traspasos para Administración" : "Déjalo donde está";
        }
        else if (kind === "co") { text = `Sage lo tiene en otra empresa: ${{ "01": "RMS", "02": "Espacio", "03": "RJB" }[first[0]] || first[0]}`; detail = "Déjalo donde está"; }
        else if (kind === "none") { text = "No está en Sage"; detail = this.state.operatorState?.session?.sage_mode === "global" ? "Se dará de alta en la revisión" : "Déjalo donde está"; }
        else if (kind === "dup") { text = `Duplicado en Sage: ${hits.map((h) => `${companyName(h[0])} · ${whName(h)} · ${stateName(h[3])}`).join(" y ")}`; detail = "Avísalo a Administración"; }
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
        if (this.state.expandedId === scanId) {
            this.state.expandedId = null;
        }
        if (operatorState && operatorState.operator) {
            this._applyState(operatorState);
        }
        this._scheduleProgress(0);
        if (this.state.inputMode === "pda") {
            this._focusInput();
        }
    }

    // Lista compacta: tocar una lectura muestra su detalle (y la papelera).
    toggleRow(scanId) {
        this.state.expandedId = this.state.expandedId === scanId ? null : scanId;
        if (this.state.inputMode === "pda") {
            this._focusInput();
        }
    }

    // Modelo corto de una lectura: la referencia entre corchetes del nombre
    // ("[A20-HH] Astral..." -> "A20-HH"), o el nombre hasta " - ".
    shortModel(scan) {
        const name = scan.product_name || "";
        if (!name) {
            return "Sin producto";
        }
        const ref = name.match(/^\[([^\]]+)\]\s*/);
        // Referencias solo numéricas (Meyer 09.237.001.02, EAN de Sony) no dicen
        // nada en el almacén: entonces el nombre ("GALILEO GALAXY 408").
        if (ref && /[A-Za-z]/.test(ref[1])) {
            return ref[1];
        }
        const rest = (ref ? name.slice(ref[0].length) : name).split(" - ")[0].split(",")[0].trim();
        return rest || (ref ? ref[1] : name);
    }

    // Motivo corto de la línea; vacío si está todo bien (verde).
    shortReason(scan, kind) {
        const sage = scan.sage || {};
        const first = (sage.h || [])[0] || [];
        const stateName = { nuevo: "Nuevo", demo: "Demo", "2mano": "2ª mano", Nuevo: "Nuevo", Demo: "Demo", "2Mano": "2ª mano" };
        const message = scan.message || "";
        switch (kind) {
            case "ok":
            case "here":
                return "";
            case "est":
                return `Sage: ${stateName[first[3]] || first[3] || "otro estado"}`;
            case "dep":
                return "En depósito en cliente";
            case "dup":
                return "Duplicado en Sage";
            case "twice":
                return `Ya contado en ${scan.also_in}`;
            case "wh":
                return `Sage lo tiene en ${first[2] || first[1] || "otro almacén"}`;
            case "co":
                return "Sage: otra empresa";
            case "none":
                return "No está en Sage";
            case "unknown":
                if (scan.suggestion) {
                    return `¿${scan.suggestion}?`;
                }
                return /varios productos/i.test(message) ? "Elige producto" :
                    /no se sigue por n/i.test(message) ? "Sin nº de serie en Odoo" :
                    /código de barras de producto|UPC/i.test(message) ? "Código de producto" : "Elige producto";
            default:
                if (scan.type === "ignored") {
                    return /código de barras del producto/i.test(message) ? "Código de producto, no cuenta" : "Ignorado";
                }
                return scan.type === "product" ? `× ${this.formatQty(scan.quantity ?? 1)}` : "";
        }
    }

    async printScanLabel(scanId) {
        try {
            const action = await this.orm.call("rms.stock.count.scan", "scanner_print_label", [[scanId]]);
            await this.action.doAction(action);
        } catch (error) {
            this.notification.add((error.data && error.data.message) || "No se pudo imprimir la etiqueta.",
                { type: "warning" });
        }
        if (this.state.inputMode === "pda") {
            this._focusInput();
        }
    }

    async changeScanState(scanId, stateId) {
        try {
            const payload = await this.orm.call(
                "rms.stock.count.scan", "scanner_change_state", [[scanId], parseInt(stateId, 10)]
            );
            const index = this.state.history.findIndex((scan) => scan.id === scanId);
            if (index >= 0) {
                this.state.history[index] = payload;
            }
            this._scheduleProgress(0);
        } catch {
            this.notification.add("No se pudo cambiar el estado. Comprueba la conexión y vuelve a intentarlo.",
                { type: "warning" });
        }
        if (this.state.inputMode === "pda") {
            this._focusInput();
        }
    }

    openPanel(panel) {
        this.state.panel = panel;
        this.state.panelQuery = "";
        this.state.panelResults = [];
        this.state.sagePick = null;
        this._resetQty();
        this.state.qtyDone = null;
        this._search();
    }

    closePanel() {
        this.state.panel = null;
        this.state.sagePick = null;
        this._resetQty();
        this.state.qtyDone = null;
    }

    // ------------------------------------------------------------------
    // "Por cantidad": artículos sin nº de serie (cables, fundas, hierros).
    // Se busca el artículo, se elige estado y se teclea la cantidad contada.
    // A ciegas: aquí nunca se enseña la cantidad que dice Sage.
    // ------------------------------------------------------------------

    _resetQty() {
        this.state.qtyPick = null;
        this.state.qtyValue = "";
        this.state.qtyConfirm = null;
        this.state.qtyEditScanId = null;
        this.state.qtyBusy = false;
    }

    formatQty(value) {
        const number = Math.round((Number(value) || 0) * 1000) / 1000;
        return String(number).replace(".", ",");
    }

    get qtyNumber() {
        return parseInt(this.state.qtyValue, 10) || 0;
    }

    pickQtyItem(rec) {
        const os = this.state.operatorState;
        this._resetQty();
        this.state.qtyDone = null;
        this.state.qtyPick = rec;
        this.state.qtyStateId = os.operator.current_state_id ||
            ((os.product_states || [])[0] || {}).id || null;
        // Un toque doble o un reenvío no apuntan dos veces la misma cantidad.
        this._qtyUid = newUid();
        if (this.qtyPanelRef.el) {
            this.qtyPanelRef.el.scrollTop = 0;
        }
    }

    // Corregir la cantidad de una lectura ya hecha, con el mismo teclado.
    openQtyEdit(scan) {
        this.state.panelQuery = "";
        this.state.panelResults = [];
        this.state.sagePick = null;
        this._resetQty();
        this.state.qtyDone = null;
        this.state.qtyPick = { key: `scan${scan.id}`, name: scan.product_name || scan.code, ok: true };
        this.state.qtyValue = String(Math.round(Number(scan.quantity) || 0) || "");
        this.state.qtyEditScanId = scan.id;
        this.state.panel = "qty";
    }

    clearQtyPick() {
        if (this.state.qtyEditScanId) {
            this.closePanel();
        } else {
            this._resetQty();
        }
    }

    setQtyState(stateId) {
        this.state.qtyStateId = stateId;
        this.state.qtyConfirm = null;
    }

    qtyKey(key) {
        if (this.state.qtyBusy) {
            return;
        }
        let value = this.state.qtyValue;
        if (key === "C") {
            value = "";
        } else if (key === "back") {
            value = value.slice(0, -1);
        } else if (value.length < 5) {
            value = (value + key).replace(/^0+(?=\d)/, "");
        }
        this.state.qtyValue = value;
        this.state.qtyConfirm = null;
    }

    onQtyInput(ev) {
        const value = ev.target.value.replace(/\D/g, "").replace(/^0+(?=\d)/, "").slice(0, 5);
        ev.target.value = value;
        this.state.qtyValue = value;
        this.state.qtyConfirm = null;
    }

    async qtySave(mode = false) {
        const rec = this.state.qtyPick;
        const qty = this.qtyNumber;
        if (!rec || !rec.ok || this.state.qtyBusy) {
            return;
        }
        if (!qty) {
            this.notification.add("Escribe la cantidad que has contado.", { type: "warning" });
            return;
        }
        const op = this.state.operatorState.operator;
        this.state.qtyBusy = true;
        try {
            if (this.state.qtyEditScanId) {
                const payload = await this._send(
                    "rms.stock.count.scan", "scanner_set_quantity", [[this.state.qtyEditScanId], qty]
                );
                this._mergeHistory([payload]);
                this.closePanel();
                this._scheduleProgress(0);
                return;
            }
            // _send siempre termina (también con un corte por tiempo agotado): el
            // botón no se queda bloqueado y repetir el apunte no duplica (mismo uid).
            const result = await this._send("rms.stock.count.operator", "scanner_qty_count",
                [[op.id], rec.product_id, qty, this.state.qtyStateId || false, mode, this._qtyUid]);
            if (result.status === "confirm") {
                this.state.qtyConfirm = result;
                return;
            }
            this._historyGeneration++;
            const deleted = new Set(result.deleted_ids || []);
            if (deleted.size) {
                this.state.history = this.state.history.filter((scan) => !deleted.has(scan.id));
            }
            this._mergeHistory([result.scan]);
            this._applyState(result.state);
            this.state.qtyDone = `Apuntado: ${this.formatQty(qty)} × ${rec.name}` +
                (result.total !== qty ? ` · total ${this.formatQty(result.total)}` : "");
            this._resetQty();
            this._feedback("ok", result.status);
            this._scheduleProgress(0);
            await this._search();
        } catch (error) {
            this.notification.add((error.data && error.data.message) || "No se pudo apuntar la cantidad. Comprueba la conexión.",
                { type: "warning" });
        } finally {
            this.state.qtyBusy = false;
        }
    }

    // "Buscar en Sage": mesa en flycase sin pegatina. Se elige de la lista de
    // lo que falta por contar en este almacén y se cuenta + imprime la etiqueta.
    pickSageLine(rec) {
        const code = { nuevo: "new", demo: "demo", "2mano": "second_hand" }[rec.state] || "new";
        const productState = (this.state.operatorState.product_states || []).find((st) => st.code === code);
        this.state.sagePick = rec;
        this.state.sagePickStateId = productState ? productState.id : null;
    }

    async sagePrintAndCount() {
        const rec = this.state.sagePick;
        const op = this.state.operatorState.operator;
        if (!rec) {
            return;
        }
        try {
            const result = await this.orm.call("rms.stock.count.operator", "scanner_sage_print_and_count",
                [[op.id], rec.id, this.state.sagePickStateId || false]);
            this._mergeHistory([result.scan]);
            this._applyState(result.state);
            this.state.panel = null;
            this.state.sagePick = null;
            this._scheduleProgress(0);
            this._feedback("ok", result.status);
            await this.action.doAction(result.action);
        } catch (error) {
            this.notification.add((error.data && error.data.message) || "No se pudo contar ni imprimir.",
                { type: "warning" });
        }
    }

    async sageNotInList() {
        this.closePanel();
        await this.openReplacementLabel();
    }

    onPanelQueryInput(ev) {
        this.state.panelQuery = ev.target.value;
        clearTimeout(this._searchTimer);
        this._searchTimer = setTimeout(() => this._search(), 300);
    }

    async _search() {
        const op = this.state.operatorState.operator;
        const method = this.state.panel === "location" ? "scanner_search_locations"
            : this.state.panel === "sage" ? "scanner_sage_search"
            : this.state.panel === "qty" ? "scanner_qty_search" : "scanner_search_products";
        const panel = this.state.panel;
        const results = await this.orm.call(
            "rms.stock.count.operator", method, [[op.id], this.state.panelQuery]
        );
        if (this.state.panel === panel) {
            this.state.panelResults = results;
        }
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
                if (this.state.inputMode === "pda") {
                    this._focusInput();
                }
            },
        });
    }

    async finish() {
        if (this._blockedByQueue("terminar")) {
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
        if (this.state.step === "scan" && this._blockedByQueue("salir")) {
            return;
        }
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
