/** @odoo-module **/

import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Component, onMounted, onPatched, onWillUnmount, useRef, useState } from "@odoo/owl";
import {
    BurstReader, QtyWriter, ScanAudio, ScanQueue, actionErrorText, callAction, errorKind, newUid, sendRpc,
    storageGet, storageSet,
} from "@rms_scan_queue/scan_queue";

// La cola de lecturas (una lectura nunca se pierde en silencio), el corte de
// ráfagas de la pistola sin Enter y el sonido son comunes a las pantallas de
// pistola: rms_scan_queue.
const REFRESH_MS = 6000;
// El código de producto leído vale para la caja siguiente, no para siempre.
const CONTEXT_TTL_MS = 30000;

const VERDICTS = {
    ok: { kind: "green", title: "Correcto" },
    probable: { kind: "amber", title: "Se parece: a revisar" },
    wrong_model: { kind: "amber", title: "Modelo distinto" },
    ambiguous: { kind: "amber", title: "Lee antes el código del producto" },
    extra: { kind: "red", title: "No está en la lista" },
    product_code: { kind: "grey", title: "Código de producto" },
    ignored: { kind: "grey", title: "No cuenta" },
    repeat: { kind: "grey", title: "Ya leído" },
    error: { kind: "red", title: "No se ha guardado" },
    queued: { kind: "grey", title: "Pendiente de enviar" },
};
const TONES = {
    green: [[1200, 0.09]],
    amber: [[650, 0.1], [650, 0.1]],
    red: [[240, 0.35]],
    grey: [[500, 0.06]],
    blue: [[900, 0.08]],
};

export class ReceptionChecklist extends Component {
    static template = "rms_stock_reception_check.Checklist";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.inputRef = useRef("codeInput");
        this.rootRef = useRef("root");
        const action = this.props.action || {};
        this.receptionId =
            (action.params && action.params.reception_id) || (action.context && action.context.active_id) || false;
        this.state = useState({
            loading: true,
            error: "",
            data: null,
            filter: "all",
            verdict: null,
            context: null,
            panel: null,
            collapsed: {},
            openLine: false,
            lastLine: false,
        });
        this._scrollTo = false;
        this._generation = 0; // sube con cada respuesta aplicada: un refresco viejo no pisa lo nuevo

        // Cola de lecturas de ESTA recepción, operario y aparato.
        const queueName = `reception.${this.receptionId}.u${user.userId}`;
        this.contextKey = `rms_scan_queue.${queueName}.context`;
        this.queueState = useState(ScanQueue.initialState());
        this.queue = new ScanQueue({
            state: this.queueState,
            name: queueName,
            dialog: this.dialog,
            notification: this.notification,
            where: "en la recepción",
            send: (item) => this._sendScan(item),
            onSaved: (item, response) => this._applyScan(response, { item }),
            onAside: (item, message) => {
                this._setVerdict("error", message, item.code);
                this._beep("red");
            },
            probe: () => this._refresh(true),
            afterAction: () => this._focusInput(),
        });
        this.reader = new BurstReader({
            state: this.queueState,
            getInput: () => this.inputRef.el,
            onCode: (code) => this._enqueue(code),
        });
        this.audio = new ScanAudio(this.queueState);
        this.qtyWriter = new QtyWriter({
            send: (lineId, quantity) =>
                callAction(this.queue, "rms.reception.line", "checklist_set_qty", [[lineId], quantity]),
            onSaved: (lineId, quantity, data, isLast) => {
                if (isLast) {
                    this._setData(data);
                    this.state.lastLine = lineId;
                }
            },
            onFailed: (lineId, confirmed, message) => {
                this._showQty(lineId, confirmed);
                this.notification.add(message, { type: "danger" });
            },
        });

        this._onGlobalKeydown = (ev) => {
            if (!this.readonly && !this.state.panel) {
                this.reader.redirectKey(ev);
            }
        };
        onMounted(() => {
            window.addEventListener("keydown", this._onGlobalKeydown, true);
            this.audio.start();
            this._load();
            this._refreshTimer = setInterval(() => this._refresh(), REFRESH_MS);
        });
        onPatched(() => this._afterPatch());
        onWillUnmount(() => {
            window.removeEventListener("keydown", this._onGlobalKeydown, true);
            clearInterval(this._refreshTimer);
            clearTimeout(this._contextTimer);
            this.queue.destroy();
            this.reader.destroy();
            this.audio.destroy();
        });
    }

    // ------------------------------------------------------------------
    // Datos
    // ------------------------------------------------------------------
    get data() {
        return this.state.data;
    }

    get readonly() {
        return !this.data || this.data.reception.state !== "receiving";
    }

    get blind() {
        return Boolean(this.data && this.data.reception.blind);
    }

    get visibleGroups() {
        const filter = this.state.filter;
        const groups = [];
        for (const group of this.data.groups) {
            const lines = group.lines.filter((line) => {
                if (filter === "pending") {
                    return !this.isDone(line);
                }
                if (filter === "done") {
                    return this.isDone(line) || line.qty_received > 0;
                }
                return true;
            });
            if (lines.length) {
                groups.push({ ...group, lines });
            }
        }
        return groups;
    }

    documentRefs(group) {
        const displayed = [group.code, group.name].filter(Boolean).join(" · ");
        const displayedReverse = [group.name, group.code].filter(Boolean).join(" · ");
        return (group.doc_refs || []).filter((ref) => ref !== displayed && ref !== displayedReverse);
    }

    isDone(line) {
        if (line.by_quantity) {
            return line.qty_received >= line.qty_expected;
        }
        return line.state !== "pending" && line.state !== "missing";
    }

    lineClass(line) {
        const classes = [`o_rms_rc_line_${line.state}`];
        if (line.by_quantity && line.qty_received > 0 && line.qty_received < line.qty_expected) {
            classes.push("o_rms_rc_line_partial");
        }
        if (line.by_quantity && line.qty_received > line.qty_expected) {
            classes.push("o_rms_rc_line_over");
        }
        if (this.state.lastLine === line.id) {
            classes.push("o_rms_rc_line_last");
        }
        return classes.join(" ");
    }

    lineStatus(line) {
        const who = line.user ? ` · ${line.user} ${line.time}` : "";
        switch (line.state) {
            case "received":
                return `Recibido${who}${line.manual ? " · escrito a mano" : ""}`;
            case "probable":
                return `Se parece a lo leído (${line.scanned_serial}): lo confirmará un responsable${who}`;
            case "wrong_model":
                return `Leído en una caja de ${line.scanned_product || "otro modelo"}: a revisar${who}`;
            case "damaged":
                return `Dañado: ${line.damage_note}${who}`;
            case "missing":
                return "Falta";
            case "extra":
                return `No estaba en la lista${who}`;
            default:
                return line.by_quantity && line.qty_received ? `Contado${who}` : "Pendiente";
        }
    }

    groupClass(group) {
        if (group.total && group.done >= group.total) {
            return "o_rms_rc_group_done";
        }
        return group.review ? "o_rms_rc_group_review" : "";
    }

    percent(group) {
        return group.total ? Math.min(100, Math.round((group.done / group.total) * 100)) : 0;
    }

    fmt(value) {
        return Number.isInteger(value) ? String(value) : String(Math.round(value * 100) / 100);
    }

    _setData(data) {
        this._generation += 1;
        this.state.data = data;
        this.state.error = "";
    }

    async _load() {
        if (!this.receptionId) {
            this.state.loading = false;
            this.state.error = "Abre esta pantalla desde una recepción.";
            return;
        }
        // Lo que quedó sin enviar en este aparato se ve (y se envía) desde ya.
        this.queue.start();
        this._restoreContext();
        const answer = await callAction(this.queue, "rms.reception", "checklist_state", [[this.receptionId]]);
        if (answer.ok) {
            this._setData(answer.result);
            this.state.error = "";
        } else if (!this.state.data) {
            this.state.error = answer.kind === "user" ? answer.message
                : "No se ha podido cargar la recepción: no hay conexión. Se vuelve a intentar sola.";
        }
        this.state.loading = false;
        this._focusInput();
    }

    // Varios operarios a la vez: se refresca lo que han leído los demás. Con
    // lecturas pendientes no se refresca: la cola trae el estado al entrar.
    async _refresh(force = false) {
        if (!this.receptionId || this.queueState.pending.length || this.qtyWriter.busy ||
                (!force && (this.state.panel || document.hidden))) {
            return;
        }
        const generation = this._generation;
        try {
            const data = await sendRpc("rms.reception", "checklist_state", [[this.receptionId]]);
            this.queue.noteOk();
            if (generation === this._generation && !this.queueState.pending.length && !this.qtyWriter.busy) {
                this.state.data = data;
                this.state.error = "";
            }
        } catch (error) {
            // Sin red un momento: se reintenta en el siguiente ciclo; el
            // indicador de la barra lo dice.
            const kind = await errorKind(error);
            this.queue.noteError(kind);
            if (kind === "user" && !this.state.data) {
                this.state.error = actionErrorText(error, kind);
            }
        }
    }

    // ------------------------------------------------------------------
    // Lectura con la pistola
    // ------------------------------------------------------------------
    _focusInput() {
        if (this.readonly || this.state.panel) {
            return;
        }
        const input = this.inputRef.el;
        if (input) {
            input.focus({ preventScroll: true });
        }
    }

    onCodeKeydown(ev) {
        this.reader.onKeydown(ev);
    }

    onCodeInput(ev) {
        this.reader.onInput(ev);
    }

    addTypedCode() {
        this.reader.submit();
        this._focusInput();
    }

    // Cada lectura queda guardada en el aparato ANTES de enviarla: o entra en
    // el servidor o sigue a la vista como pendiente / con error.
    _enqueue(rawCode) {
        const code = (rawCode || "").trim();
        if (!code) {
            return;
        }
        if (this.readonly) {
            this.notification.add(`La recepción ya no admite lecturas: «${code}» no se ha guardado.`,
                { type: "danger", sticky: true });
            return;
        }
        this.queue.enqueue(code);
        if (this.queueState.conn !== "ok") {
            this._setVerdict("queued", "Guardada en este dispositivo: se enviará sola al volver la conexión.", code);
        }
    }

    // El orden importa: código de producto y luego nº de serie. La cola envía
    // de una en una y en orden, así el producto de la lectura anterior ya se
    // conoce cuando le toca a la siguiente (aunque hayan esperado sin red).
    _sendScan(item) {
        const context = this._contextFor(item);
        return sendRpc("rms.reception", "checklist_scan", [[this.receptionId], item.code], {
            product_id: context ? context.id : false,
            client_uid: item.uid,
        });
    }

    _applyScan(response, options = {}) {
        const result = response.result;
        this._setData(response.state);
        const at = options.item ? options.item.at : Date.now();
        if (result.sets_context) {
            this._setContext({ id: result.product_id, name: result.product_name, at });
        } else if (!["product_code", "ignored", "repeat"].includes(result.verdict)) {
            // El código de producto leído solo vale para UNA caja.
            this._setContext(null);
        }
        if (!options.silent) {
            this._setVerdict(result.verdict, result.message, result.code);
            const colour = this.state.verdict.kind;
            this._beep(colour);
        }
        if (result.line_id) {
            this.state.lastLine = result.line_id;
            this._scrollTo = result.line_id;
            for (const group of response.state.groups) {
                if (group.lines.some((line) => line.id === result.line_id)) {
                    this.state.collapsed[group.key] = false;
                }
            }
            if (this.state.filter === "pending" && result.verdict === "ok") {
                // En «Faltan» la línea recién leída desaparece de la vista: es lo esperado.
                this._scrollTo = false;
            }
        }
    }

    _setVerdict(verdict, message, code) {
        const base = VERDICTS[verdict] || VERDICTS.error;
        let kind = base.kind;
        let title = base.title;
        if (verdict === "extra" && this.blind) {
            kind = "blue";
            title = "Leído (sin lista todavía)";
        }
        this.state.verdict = { kind, title, message: message || "", code: code || "" };
    }

    // El código de producto vale para la caja leída DESPUÉS, dentro de los
    // 30 s siguientes (hora de lectura, no de envío: sin red también vale).
    _contextFor(item) {
        const context = this.state.context;
        if (context && item.at >= context.at && item.at - context.at <= CONTEXT_TTL_MS) {
            return context;
        }
        return null;
    }

    _currentContext() {
        const context = this.state.context;
        if (context && Date.now() - context.at > CONTEXT_TTL_MS && !this.queueState.pending.length) {
            this._setContext(null);
            return null;
        }
        return context;
    }

    _setContext(product) {
        clearTimeout(this._contextTimer);
        if (!product) {
            this.state.context = null;
            storageSet(this.contextKey, null);
            return;
        }
        this.state.context = { id: product.id, name: product.name, at: product.at || Date.now() };
        storageSet(this.contextKey, JSON.stringify(this.state.context));
        this._armContextTimer();
    }

    _armContextTimer() {
        clearTimeout(this._contextTimer);
        const context = this.state.context;
        if (!context) {
            return;
        }
        const left = Math.max(context.at + CONTEXT_TTL_MS - Date.now(), 0);
        this._contextTimer = setTimeout(() => {
            if (this.queueState.pending.length) {
                // Aún hay lecturas esperando que pueden necesitarlo.
                this._contextTimer = setTimeout(() => this._armContextTimer(), 1000);
            } else {
                this._setContext(null);
            }
        }, left);
    }

    // Tras recargar: el producto leído justo antes sigue valiendo para las
    // lecturas que quedaron pendientes.
    _restoreContext() {
        try {
            const context = JSON.parse(storageGet(this.contextKey) || "null");
            if (context && context.id && context.at) {
                this.state.context = context;
                this._armContextTimer();
            }
        } catch { /* sin contexto guardado */ }
    }

    clearContext() {
        this._setContext(null);
        this._focusInput();
    }

    _afterPatch() {
        if (!this._scrollTo || !this.rootRef.el) {
            return;
        }
        const row = this.rootRef.el.querySelector(`[data-line="${this._scrollTo}"]`);
        this._scrollTo = false;
        if (row && row.scrollIntoView) {
            row.scrollIntoView({ block: "nearest", behavior: "smooth" });
        }
    }

    // ------------------------------------------------------------------
    // Sonido (opcional)
    // ------------------------------------------------------------------
    _beep(kind) {
        this.audio.play(TONES[kind] || TONES.grey);
    }

    // ------------------------------------------------------------------
    // Botones
    // ------------------------------------------------------------------
    // Botones que no son lecturas: no van a la cola. La llamada siempre
    // termina (también con un corte por tiempo agotado) y, si falla, se dice
    // claro y el botón queda libre para volver a pulsar.
    async _call(model, method, args, kwargs = {}) {
        const answer = await callAction(this.queue, model, method, args, kwargs);
        if (!answer.ok) {
            this.notification.add(answer.message, { type: "danger" });
            return null;
        }
        return answer.result;
    }

    setFilter(filter) {
        this.state.filter = filter;
        this._focusInput();
    }

    toggleGroup(group) {
        this.state.collapsed[group.key] = !this.state.collapsed[group.key];
    }

    toggleLine(line) {
        if (this.readonly) {
            return;
        }
        this.state.openLine = this.state.openLine === line.id ? false : line.id;
    }

    async undo(scanId) {
        if (this.readonly || this._undoing || this.queue.blocked("deshacer")) {
            return;
        }
        if (!scanId) {
            // Se deshace UNA lectura concreta (la última mía a la vista): si
            // la respuesta se pierde y se vuelve a pulsar, no se deshace otra.
            const mine = this.data.scans.find((scan) => scan.mine && scan.can_undo);
            scanId = mine ? mine.id : false;
        }
        this._undoing = true;
        const response = await this._call("rms.reception", "checklist_undo", [[this.receptionId]], {
            scan_id: scanId || false,
        });
        this._undoing = false;
        if (response) {
            this._setData(response.state);
            this.state.lastLine = false;
            this.state.verdict = { kind: "grey", title: "Deshecho", message: `Se ha quitado la lectura ${response.undone}.`, code: "" };
        }
        this._focusInput();
    }

    async unreceive(line) {
        const data = await this._call("rms.reception.line", "checklist_unreceive", [[line.id]]);
        if (data) {
            this._setData(data);
            this.state.openLine = false;
        }
        this._focusInput();
    }

    changeQty(line, delta) {
        this.setQty(line, Math.max(0, line.qty_received + delta));
    }

    onQtyChange(line, ev) {
        const value = parseFloat(String(ev.target.value).replace(",", "."));
        if (Number.isNaN(value)) {
            ev.target.value = this.fmt(line.qty_received);
            return;
        }
        this.setQty(line, Math.max(0, value));
    }

    // + y −: se envía la cantidad FINAL (no "+1"), de una en una. Un doble
    // toque o un reenvío no cuentan dos veces; si falla, vuelve a lo guardado.
    setQty(line, quantity) {
        if (this.readonly) {
            return;
        }
        const confirmed = line.qty_received;
        this._showQty(line.id, quantity);
        this.qtyWriter.set(line.id, quantity, confirmed);
    }

    _showQty(lineId, quantity) {
        for (const group of this.data.groups) {
            for (const line of group.lines) {
                if (line.id === lineId) {
                    line.qty_received = quantity;
                }
            }
        }
        for (const extra of this.data.extras) {
            if (extra.id === lineId) {
                extra.qty_received = quantity;
            }
        }
    }

    // --- Dañado ---
    openDamaged(line) {
        this.state.panel = { type: "damaged", line, note: line.damage_note || "", error: "" };
    }

    async saveDamaged() {
        const panel = this.state.panel;
        if (!panel.note.trim()) {
            panel.error = "Escribe qué daño tiene la caja.";
            return;
        }
        const data = await this._call("rms.reception.line", "checklist_set_damaged", [[panel.line.id]], {
            note: panel.note,
        });
        if (data) {
            this._setData(data);
            this.closePanel();
        }
    }

    async clearDamaged(line) {
        const data = await this._call("rms.reception.line", "checklist_set_damaged", [[line.id]], { damaged: false });
        if (data) {
            this._setData(data);
        }
        this._focusInput();
    }

    // --- Sin etiqueta ---
    openNoLabel(group) {
        const context = this._currentContext();
        const products = this.data.groups.filter((g) => g.product_id && g.tracked);
        let productId = group && group.product_id ? group.product_id : context ? context.id : false;
        if (!productId && products.length === 1) {
            productId = products[0].product_id;
        }
        // uid: volver a pulsar Guardar tras un corte no duplica la lectura.
        this.state.panel = { type: "nolabel", products, productId, serial: "", confirm: "", error: "", print: true,
            uid: newUid(), busy: false };
    }

    async saveNoLabel() {
        const panel = this.state.panel;
        const serial = panel.serial.trim();
        if (!serial) {
            panel.error = "Escribe el número de serie que pone en la placa del equipo.";
            return;
        }
        if (serial !== panel.confirm.trim()) {
            panel.error = "Los dos números no coinciden. Vuelve a mirar la placa del equipo.";
            return;
        }
        if (panel.busy) {
            return;
        }
        panel.busy = true;
        panel.error = "";
        const answer = await callAction(
            this.queue, "rms.reception", "checklist_manual_serial", [[this.receptionId], serial, panel.confirm.trim()],
            { product_id: panel.productId ? Number(panel.productId) : false, print_label: panel.print,
                client_uid: panel.uid }
        );
        panel.busy = false;
        if (!answer.ok) {
            panel.error = answer.message;
            return;
        }
        const response = answer.result;
        this.closePanel();
        this._applyScan(response);
        if (response.print_action) {
            await this.action.doAction(response.print_action);
        } else if (response.print_message) {
            this.notification.add(response.print_message, { type: "warning", sticky: true });
        }
    }

    closePanel() {
        this.state.panel = null;
        setTimeout(() => this._focusInput(), 50);
    }

    // --- Documento, terminar, volver ---
    async loadDocument() {
        const action = await this._call("rms.reception", "action_load_document", [[this.receptionId]]);
        if (action) {
            await this.action.doAction(action, { onClose: () => this._load() });
        }
    }

    finish() {
        // Con lecturas sin enviar o con error no se termina: se quedarían fuera.
        if (this.queue.blocked("terminar")) {
            return;
        }
        const counters = this.data.counters;
        const missing = counters.missing
            ? `Quedan ${this.fmt(counters.missing)} sin leer: pasarán a «Falta». `
            : "Está todo leído. ";
        this.dialog.add(ConfirmationDialog, {
            title: "¿Has terminado?",
            body: `${missing}La recepción pasará al responsable para revisarla y dar entrada en stock.`,
            confirmLabel: "Sí, he terminado",
            cancelLabel: "Seguir leyendo",
            confirm: async () => {
                if (this.queue.blocked("terminar")) {
                    return;
                }
                const done = await this._call("rms.reception", "action_finish", [[this.receptionId]]);
                if (done) {
                    this._openForm();
                }
            },
            cancel: () => this._focusInput(),
        });
    }

    openForm() {
        if (!this.readonly && this.queue.blocked("salir")) {
            return;
        }
        this._openForm();
    }

    _openForm() {
        this.action.doAction(
            {
                type: "ir.actions.act_window",
                res_model: "rms.reception",
                res_id: this.receptionId,
                views: [[false, "form"]],
                target: "current",
            },
            { clearBreadcrumbs: true }
        );
    }
}

registry.category("actions").add("rms_stock_reception_check.checklist", ReceptionChecklist);
