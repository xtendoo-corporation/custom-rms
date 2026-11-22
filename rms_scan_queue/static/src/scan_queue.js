/** @odoo-module **/

// Librería común de las pantallas de pistola (recepción, salida, depósitos).
// Garantía: UNA LECTURA NUNCA SE PIERDE EN SILENCIO. O está guardada en el
// servidor, o está a la vista como «Pendiente de enviar» o «con error».
// Mismo diseño (y mismos valores, ya probados) que el escáner del recuento.

import { browser } from "@web/core/browser/browser";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { ConnectionLostError, rpc } from "@web/core/network/rpc";
import { user } from "@web/core/user";
import { session } from "@web/session";

// Lector sin Enter: ráfaga de >= 4 caracteres a < 45 ms de media por tecla =
// una lectura. Se cierra con 160 ms de pausa o en cuanto empieza la siguiente
// (un hueco de más de 90 ms entre teclas), así dos lecturas seguidas no se
// funden. Un tropiezo del Bluetooth de hasta 90 ms dentro de un código no lo
// parte.
const BURST_GAP_MS = 45;
const BURST_JOIN_MS = 90;
const BURST_PAUSE_MS = 160;
const BURST_MIN_CHARS = 4;
const STUCK_INPUT_MS = 1000;
// Reintentos de la cola con espera creciente mientras haya pendientes.
const RETRY_STEPS_MS = [2000, 4000, 8000, 16000, 30000];
// Una llamada que no contesta en este tiempo se da por fallida y se reintenta
// (el navegador no avisa de un corte "por tiempo agotado").
const SEND_TIMEOUT_MS = 25000;
// Errores internos del servidor seguidos para UNA lectura antes de apartarla.
const MAX_SERVER_TRIES = 5;
const SLOW_QUEUE_MS = 1500;
// Errores del propio programa (validación): reintentar no cambia nada.
const USER_ERRORS = new Set([
    "odoo.exceptions.UserError", "odoo.exceptions.ValidationError", "odoo.exceptions.AccessError",
    "odoo.exceptions.MissingError", "odoo.exceptions.AccessDenied", "odoo.exceptions.RedirectWarning",
]);

export function storageGet(key) {
    try {
        return window.localStorage.getItem(key);
    } catch {
        return null;
    }
}

export function storageSet(key, value) {
    try {
        if (value === null) {
            window.localStorage.removeItem(key);
        } else {
            window.localStorage.setItem(key, value);
        }
        return true;
    } catch {
        return false;
    }
}

export function newUid() {
    if (window.crypto && window.crypto.randomUUID) {
        return window.crypto.randomUUID();
    }
    return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

// Llamada al servidor que SIEMPRE termina: el rpc de Odoo no resuelve ni
// rechaza cuando el navegador corta por tiempo agotado (evento "timeout"), y
// la cola (o el botón) se quedaba esperando para siempre.
export function sendRpc(model, method, args, kwargs = {}) {
    const url = `/web/dataset/call_kw/${model}/${method}`;
    const xhr = new browser.XMLHttpRequest();
    const promise = new Promise((resolve, reject) => {
        const lost = () => reject(new ConnectionLostError(url));
        xhr.addEventListener("timeout", lost);
        xhr.addEventListener("abort", lost);
        const { context, ...rest } = kwargs;
        const request = rpc(url, { model, method, args, kwargs: { ...rest, context: { ...user.context, ...(context || {}) } } },
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

async function serverAlive() {
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

// Qué ha fallado: "expired" (sesión caducada), "network" (sin red o servidor
// caído: reintentar siempre), "server" (error interno: reintentar unas cuantas
// veces) o "user" (el programa rechaza la lectura o la acción: mostrar).
export async function errorKind(error) {
    const name = error && (error.exceptionName || (error.data && error.data.name)) || "";
    if (error && error.name === "RPC_ERROR") {
        if (error.code === 100 || /SessionExpired/.test(name)) { return "expired"; }
        return USER_ERRORS.has(name) ? "user" : "server";
    }
    if (error && /\/web\/login/.test(error.responseURL || "")) { return "expired"; }
    if (error && error.httpStatus === 404) {
        // Sin sesión Odoo no sabe qué base es y contesta 404 a las llamadas;
        // si el servidor sí responde a una consulta pública, es la sesión.
        return (await serverAlive()) ? "expired" : "network";
    }
    return "network";
}

function errorDetail(error) {
    const data = error && error.data;
    return (data && (data.message || (data.arguments && data.arguments[0]))) || "";
}

// Texto para una LECTURA que no entra.
function readingErrorText(error, kind) {
    if (kind === "user") {
        return errorDetail(error) || "El programa no admite esta lectura.";
    }
    return "El servidor ha dado un error al guardar esta lectura. Pulsa Reintentar; " +
        "si sigue igual, avisa al responsable.";
}

// Texto para un BOTÓN (He terminado, validar, +/−, Revisado, Dañado...) que
// no ha podido guardar. No va a la cola: se vuelve a pulsar.
export function actionErrorText(error, kind) {
    if (kind === "user") {
        return errorDetail(error) || "El programa no admite esta acción.";
    }
    if (kind === "expired") {
        return "No se ha podido guardar: tu sesión ha caducado. Vuelve a entrar y pulsa otra vez.";
    }
    if (kind === "server") {
        return "No se ha podido guardar: el servidor ha dado un error. Vuelve a pulsar; si sigue igual, avisa al responsable.";
    }
    return "No se ha podido guardar: no hay conexión. Vuelve a pulsar cuando vuelva.";
}

// Enlace para volver a entrar SIEMPRE en la misma base de datos y pantalla.
export function loginUrl() {
    const here = window.location.pathname + window.location.search + window.location.hash;
    return `/web/login?db=${encodeURIComponent(session.db || "")}&redirect=${encodeURIComponent(here)}`;
}

const CONN_OF = { expired: "expired", server: "server", network: "offline" };

// ----------------------------------------------------------------------
// Cola de envío: cada lectura se guarda en el aparato hasta que el servidor
// la confirma. Si se cae la Wi-Fi se reintenta sola; el uid evita que un
// reenvío cuente dos veces la misma lectura. Se envía EN ORDEN: mientras la
// primera esté pendiente por red o servidor, las siguientes esperan.
// ----------------------------------------------------------------------
export class ScanQueue {
    static initialState() {
        return {
            pending: [], // [{uid, code, at, tries}] lecturas aún no confirmadas por el servidor
            failed: [], // [{uid, code, error}] lecturas que el servidor rechaza: a revisar
            conn: "ok", // ok | offline | server | expired
            queueSlow: false, // hay pendientes desde hace más de SLOW_QUEUE_MS
            sendingUid: null,
            stuck: false, // texto sin procesar en la casilla de lectura
            audioLocked: false,
        };
    }

    /**
     * @param {Object} options
     * @param {Object} options.state estado reactivo (useState(ScanQueue.initialState()))
     * @param {string} options.name cola de ESTE documento y operario, p. ej. "reception.12.u7"
     * @param {Function} options.send (item) => sendRpc(...): envía una lectura con item.uid como client_uid
     * @param {Function} options.onSaved (item, result): el servidor ha guardado la lectura
     * @param {Function} [options.reject] (item, result) => texto si la respuesta no vale como guardada
     * @param {Function} [options.onAside] (item, message): lectura apartada por error
     * @param {Function} [options.probe] () => comprueba la conexión cuando no hay pendientes
     * @param {Function} [options.afterAction] () => devuelve el foco a la casilla de lectura
     * @param {Object} options.dialog servicio de diálogos
     * @param {Object} options.notification servicio de avisos
     * @param {string} [options.where] "en la recepción", "en el albarán"...
     */
    constructor(options) {
        Object.assign(this, { reject: () => false, onAside: () => {}, probe: () => {}, afterAction: () => {},
            where: "" }, options);
        const base = `rms_scan_queue.${session.db || ""}.${this.name}`;
        this.queueKey = `${base}.queue`;
        this.failedKey = `${base}.failed`;
        this._sending = false;
        this._retryTimer = null;
        this._retryStep = 0;
        this._gone = new Set(); // uids ya guardados o descartados en esta pestaña
        this._activeXhr = null;
        this._allowUnload = false;
        this._started = false;
        this._destroyed = false;

        // La cola se reintenta sola al volver la red, el foco o la pestaña.
        this._onWake = () => {
            if (!document.hidden) { this.retryNow(false); }
        };
        this._onOffline = () => {
            if (this._started) { this.state.conn = "offline"; }
        };
        this._onStorage = (ev) => {
            if (ev.key && ev.key === this.queueKey && this._started) {
                this._adoptStored();
                this.flush();
            }
        };
        this._onBeforeUnload = (ev) => {
            if (!this._allowUnload && (this.state.pending.length || this.state.failed.length)) {
                ev.preventDefault();
                ev.returnValue = "Hay lecturas sin enviar.";
                return ev.returnValue;
            }
        };
    }

    start() {
        if (this._started || this._destroyed) {
            return;
        }
        this._started = true;
        window.addEventListener("online", this._onWake);
        window.addEventListener("offline", this._onOffline);
        window.addEventListener("focus", this._onWake);
        document.addEventListener("visibilitychange", this._onWake);
        window.addEventListener("storage", this._onStorage);
        window.addEventListener("beforeunload", this._onBeforeUnload);
        this.state.pending = this._readStored(this.queueKey);
        this.state.failed = this._readStored(this.failedKey);
        this._touchQueueClock();
        this.flush();
    }

    destroy() {
        this._destroyed = true;
        window.removeEventListener("online", this._onWake);
        window.removeEventListener("offline", this._onOffline);
        window.removeEventListener("focus", this._onWake);
        document.removeEventListener("visibilitychange", this._onWake);
        window.removeEventListener("storage", this._onStorage);
        window.removeEventListener("beforeunload", this._onBeforeUnload);
        clearTimeout(this._retryTimer);
        clearTimeout(this._slowTimer);
    }

    // ------------------------------------------------------------ a la vista
    get busy() {
        return this.state.pending.length > 0 || this.state.failed.length > 0;
    }

    get pendingRows() {
        return [...this.state.pending].reverse();
    }

    // Indicador fijo de la barra: dónde están ahora mismo las lecturas.
    get status() {
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

    // Se calcula al pintar: al montar la pantalla la dirección aún es la anterior.
    get loginUrl() {
        return loginUrl();
    }

    onLoginClick() {
        // Las lecturas pendientes están guardadas en el dispositivo: sin aviso de salida.
        this._allowUnload = true;
    }

    // Con lecturas sin enviar o con error no se termina ni se sale: se
    // quedarían sin guardar. Devuelve true (y avisa) si hay que esperar.
    blocked(action) {
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

    // Resultado de otra llamada (refresco, botón): pone al día el indicador.
    noteOk() {
        if (this._destroyed) {
            return;
        }
        if (!this.state.pending.length) {
            this.state.conn = "ok";
        } else if (!this._sending && this.state.conn !== "ok") {
            this._retryStep = 0;
            this.flush();
        }
    }

    noteError(kind) {
        if (!this._destroyed && CONN_OF[kind]) {
            this.state.conn = CONN_OF[kind];
        }
    }

    // -------------------------------------------------------------- guardado
    _readStored(key) {
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
        storageSet(this.queueKey, this.state.pending.length ? JSON.stringify(this.state.pending) : null);
        storageSet(this.failedKey, this.state.failed.length ? JSON.stringify(this.state.failed) : null);
    }

    /** Lectura nueva: queda guardada en el aparato antes de intentar enviarla. */
    enqueue(code, extra = {}) {
        code = (code || "").trim();
        if (!code || this._destroyed) {
            return null;
        }
        const item = { uid: newUid(), code, at: Date.now(), ...extra };
        this.state.pending.push(item);
        this._saveQueue();
        this._touchQueueClock();
        // Con el servidor dando errores se respeta la espera: cada lectura
        // nueva no debe gastar un intento de la que está a la cabeza.
        if (!(this._retryTimer && this.state.conn === "server")) {
            this.flush();
        }
        return item;
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
        this._retryTimer = setTimeout(() => this.flush(), delay);
    }

    // Botón "Reintentar ahora", vuelta de la red o de la pestaña.
    retryNow(byUser = true) {
        if (!this._started || this._destroyed) {
            return;
        }
        this._retryStep = 0;
        if (!this.state.pending.length) {
            if (this.state.conn !== "ok") { this.probe(); }
        } else if (!this._sending) {
            this.flush();
        } else if (byUser && this._activeXhr && Date.now() - this._sendStarted > 3000) {
            // Envío colgado: se corta y se manda otra vez (el servidor no duplica).
            this._resendAfterAbort = true;
            this._activeXhr.abort();
        }
        if (byUser) {
            this.afterAction();
        }
    }

    // Lectura que el servidor rechaza: se aparta a "Lecturas con error" (a la
    // vista, con Reintentar/Descartar) y la cola sigue con las demás.
    _setAside(item, message) {
        this._dropPending(item.uid);
        const { tries, ...rest } = item;
        this.state.failed.push({ ...rest, error: message });
        this._saveQueue();
        this._touchQueueClock();
        try {
            this.onAside(item, message);
        } catch { /* el aviso no debe parar la cola */ }
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
        this.flush();
        this.afterAction();
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
            body: `¿Descartar la lectura «${item.code}»? No se guardará${this.where ? " " + this.where : ""}.`,
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
        }, { onClose: () => this.afterAction() });
    }

    async flush() {
        if (this._sending || !this._started) {
            return;
        }
        this._sending = true;
        clearTimeout(this._retryTimer);
        this._retryTimer = null;
        try {
            while (this.state.pending.length && !this._destroyed) {
                const item = this.state.pending[0];
                let result;
                try {
                    this.state.sendingUid = item.uid;
                    const request = this.send(item);
                    this._activeXhr = request.xhr || null;
                    this._sendStarted = Date.now();
                    result = await request;
                } catch (error) {
                    this._activeXhr = null;
                    this.state.sendingUid = null;
                    if (this._resendAfterAbort) {
                        this._resendAfterAbort = false;
                        continue;
                    }
                    const kind = await errorKind(error);
                    if (this._destroyed) {
                        return;
                    }
                    if (kind === "user") {
                        // El programa rechaza ESTA lectura: reintentar en bucle
                        // no sirve; se enseña y la cola sigue con las demás.
                        this._setAside(item, readingErrorText(error, kind));
                        continue;
                    }
                    if (kind === "server") {
                        item.tries = (item.tries || 0) + 1;
                        if (item.tries > MAX_SERVER_TRIES) {
                            this._setAside(item, readingErrorText(error, kind));
                            continue;
                        }
                        this._saveQueue();
                    }
                    // Sin red, servidor caído, error interno o sesión caducada:
                    // la lectura se queda en la cola (y las de detrás esperan
                    // su turno) y se reintenta sola.
                    this.state.conn = CONN_OF[kind] || "offline";
                    this._scheduleRetry();
                    return;
                }
                this._activeXhr = null;
                this._resendAfterAbort = false;
                this.state.sendingUid = null;
                this.state.conn = "ok";
                this._retryStep = 0;
                const refused = this.reject(item, result);
                if (refused) {
                    this._setAside(item, refused);
                    continue;
                }
                this._gone.add(item.uid);
                this._dropPending(item.uid);
                this._saveQueue();
                this._touchQueueClock();
                try {
                    this.onSaved(item, result);
                } catch (error) {
                    // La lectura YA está guardada: un fallo al pintarla no para la cola.
                    console.error(error);
                }
            }
        } finally {
            this._sending = false;
            this.state.sendingUid = null;
        }
    }
}

// ----------------------------------------------------------------------
// Botones que no son lecturas (He terminado, validar, +/−, Revisado,
// Dañado...): NO van a la cola. La llamada siempre termina (el botón queda
// libre) y, si falla, devuelve un texto claro para volver a pulsar.
// ----------------------------------------------------------------------
export async function callAction(queue, model, method, args, kwargs = {}) {
    try {
        const result = await sendRpc(model, method, args, kwargs);
        if (queue) { queue.noteOk(); }
        return { ok: true, result };
    } catch (error) {
        const kind = await errorKind(error);
        if (queue) { queue.noteError(kind); }
        return { ok: false, kind, message: actionErrorText(error, kind) };
    }
}

// Cantidades con + y −: se envía SIEMPRE la cantidad final (nunca "+1"), de
// una en una y solo la última pedida, así un doble toque o un reenvío no
// cuentan dos veces. Si falla, se vuelve a la última cantidad guardada.
export class QtyWriter {
    /**
     * @param {Function} options.send (key, qty) => Promise<{ok, result, message}>
     * @param {Function} options.onSaved (key, qty, result, isLast)
     * @param {Function} options.onFailed (key, confirmedQty, message)
     */
    constructor(options) {
        Object.assign(this, options);
        this._entries = new Map();
    }

    get busy() {
        return [...this._entries.values()].some((entry) => entry.running);
    }

    /** confirmed: cantidad que el servidor tiene ahora (para deshacer si falla). */
    set(key, qty, confirmed) {
        let entry = this._entries.get(key);
        if (!entry) {
            entry = { confirmed, target: qty, running: false };
            this._entries.set(key, entry);
        }
        if (!entry.running) {
            entry.confirmed = confirmed;
        }
        entry.target = qty;
        if (!entry.running) {
            this._run(key, entry);
        }
    }

    async _run(key, entry) {
        entry.running = true;
        try {
            while (entry.target !== entry.confirmed) {
                const qty = entry.target;
                const answer = await this.send(key, qty);
                if (!answer.ok) {
                    entry.target = entry.confirmed;
                    this.onFailed(key, entry.confirmed, answer.message);
                    return;
                }
                entry.confirmed = qty;
                this.onSaved(key, qty, answer.result, entry.target === qty);
            }
        } finally {
            entry.running = false;
            this._entries.delete(key);
        }
    }
}

// ----------------------------------------------------------------------
// Casilla de lectura: pistola sin Enter (ráfagas), con Enter/Tab o tecleado.
// ----------------------------------------------------------------------
export class BurstReader {
    /**
     * @param {Object} options.state estado reactivo con "stuck"
     * @param {Function} options.getInput () => casilla de lectura (o null)
     * @param {Function} options.onCode (code) => lectura completa
     */
    constructor(options) {
        Object.assign(this, options);
        this._burst = null;
    }

    destroy() {
        clearTimeout(this._burstTimer);
        clearTimeout(this._stuckTimer);
    }

    // Terminador del lector (Enter o Tab) o botón Añadir: todo lo que hay en
    // la casilla es una lectura.
    submit(input = this.getInput()) {
        if (!input) {
            return;
        }
        this.reset();
        const code = input.value;
        input.value = "";
        this.watch(input);
        this.onCode(code);
    }

    onKeydown(ev) {
        // Enter siempre; Tab solo si hay algo leído (sin texto, Tab navega).
        if (ev.key !== "Enter" && !(ev.key === "Tab" && ev.target.value && !ev.shiftKey)) {
            return;
        }
        ev.preventDefault();
        this.submit(ev.target);
    }

    // El lector "teclea" el código entero en pocos milisegundos y una persona
    // no. Una ráfaga rápida seguida de una pausa se envía sola como lectura.
    onInput(ev) {
        const input = ev.target;
        if (ev.inputType && ev.inputType.startsWith("delete")) {
            this.reset();
            this.watch(input);
            return;
        }
        // Hora de la tecla, no la de proceso: con la pantalla ocupada los
        // eventos llegan a trompicones y dos lecturas parecerían una sola.
        const now = ev.timeStamp || performance.now();
        const burst = this._burst;
        if (burst && now - burst.last <= BURST_JOIN_MS) {
            burst.last = now;
            burst.chars += 1;
        } else {
            let from = Math.max(0, input.value.length - 1);
            if (burst && this._isScannerBurst(burst) && burst.from < from) {
                // Empieza otra lectura sin que la anterior llegara a su pausa
                // (doble gatillo, lecturas a 100 ms): la anterior está
                // completa y se envía ya; no se funden.
                const code = input.value.slice(burst.from, from);
                input.value = input.value.slice(0, burst.from) + input.value.slice(from);
                from = burst.from;
                this._burst = null;
                this.onCode(code);
            }
            this._burst = { start: now, last: now, chars: 1, from };
        }
        clearTimeout(this._burstTimer);
        this._burstTimer = setTimeout(() => this._flushBurst(input), BURST_PAUSE_MS);
        this.watch(input);
    }

    _isScannerBurst(burst) {
        return burst.chars >= BURST_MIN_CHARS &&
            (burst.last - burst.start) / (burst.chars - 1) <= BURST_GAP_MS;
    }

    _flushBurst(input) {
        const burst = this._burst;
        this.reset();
        if (!burst || !input || !this._isScannerBurst(burst)) {
            this.watch(input);
            return;
        }
        const code = input.value.slice(burst.from);
        input.value = input.value.slice(0, burst.from);
        this.watch(input);
        this.onCode(code);
    }

    // Nunca texto pegado en la casilla sin enviar ni avisar: si queda algo
    // sin procesar más de 1 s, se avisa en ámbar.
    watch(input) {
        clearTimeout(this._stuckTimer);
        if (!input || !input.value) {
            this.state.stuck = false;
            return;
        }
        this._stuckTimer = setTimeout(() => {
            const el = this.getInput();
            this.state.stuck = Boolean(el && el.value && !this._burst);
            if (el && el.value && this._burst) { this.watch(el); }
        }, STUCK_INPUT_MS);
    }

    reset() {
        clearTimeout(this._burstTimer);
        this._burst = null;
    }

    // Pistola lista desde el primer momento: si el foco no está en un campo
    // de texto (se tocó una línea, un botón...), lo que "teclee" la pistola
    // se lleva a la casilla de lectura en vez de perderse.
    redirectKey(ev) {
        if (ev.ctrlKey || ev.metaKey || ev.altKey || ev.isComposing) {
            return;
        }
        const input = this.getInput();
        const target = ev.target;
        if (!input || target === input) {
            return;
        }
        // Escribiendo en otro campo o con un diálogo abierto: no se toca.
        if (target && target.closest &&
                target.closest("input, textarea, select, [contenteditable='true'], .modal")) {
            return;
        }
        if (document.querySelector(".modal.show, .o_dialog")) {
            return;
        }
        if (ev.key === "Enter" || ev.key === "Tab") {
            if (input.value) {
                ev.preventDefault();
                ev.stopPropagation();
                this.submit(input);
            }
            return;
        }
        if (ev.key.length !== 1) {
            return;
        }
        ev.preventDefault();
        ev.stopPropagation();
        input.focus({ preventScroll: true });
        input.value += ev.key;
        this.onInput({ target: input, timeStamp: ev.timeStamp });
    }
}

// ----------------------------------------------------------------------
// Sonido: el navegador no deja sonar nada hasta el primer toque o tecla
// (p. ej. tras recargar). Mientras esté bloqueado se avisa.
// ----------------------------------------------------------------------
export class ScanAudio {
    constructor(state) {
        this.state = state;
        this._onGesture = () => {
            if (this.state.audioLocked) { this.unlock(); }
        };
    }

    start() {
        for (const name of ["pointerdown", "touchend", "keydown"]) {
            window.addEventListener(name, this._onGesture, true);
        }
        this.unlock();
    }

    destroy() {
        this._destroyed = true;
        for (const name of ["pointerdown", "touchend", "keydown"]) {
            window.removeEventListener(name, this._onGesture, true);
        }
        this._audio?.close().catch(() => {});
    }

    unlock() {
        try {
            const AudioCtx = window.AudioContext || window.webkitAudioContext;
            if (!this._audio && AudioCtx) {
                this._audio = new AudioCtx();
                this._audio.onstatechange = () => this._check();
            }
            this._audio?.resume().then(() => this._check()).catch(() => {});
            setTimeout(() => this._check(), 400);
            // Un oscilador mudo "despierta" el sonido en el gesto real de iOS.
            if (this._audio) {
                const osc = this._audio.createOscillator();
                const gain = this._audio.createGain();
                gain.gain.value = 0;
                osc.connect(gain); gain.connect(this._audio.destination);
                osc.start(); osc.stop(this._audio.currentTime + 0.01);
            }
        } catch { /* el sonido es opcional */ }
    }

    _check() {
        if (!this._destroyed) {
            this.state.audioLocked = Boolean(this._audio && this._audio.state !== "running");
        }
    }

    /** tones: [[frecuencia, segundos], ...] */
    play(tones) {
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
        } catch { /* se sigue leyendo aunque no suene */ }
    }
}
