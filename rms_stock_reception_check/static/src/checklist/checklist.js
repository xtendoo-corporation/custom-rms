/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Component, onMounted, onPatched, onWillUnmount, useRef, useState } from "@odoo/owl";

// La pistola Honeywell viene de fábrica SIN Enter al final: "teclea" el código
// entero en pocos milisegundos. Una ráfaga de >= 4 caracteres con < 45 ms
// entre teclas seguida de 160 ms de pausa es una lectura completa.
// (Mismos valores, ya probados, que el escáner de rms_stock_count_session.)
const BURST_GAP_MS = 45;
const BURST_PAUSE_MS = 160;
const BURST_MIN_CHARS = 4;
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
};
const TONES = {
    green: [[1200, 0.09]],
    amber: [[650, 0.1], [650, 0.1]],
    red: [[240, 0.35]],
    grey: [[500, 0.06]],
    blue: [[900, 0.08]],
};

function newUid() {
    if (window.crypto && window.crypto.randomUUID) {
        return window.crypto.randomUUID();
    }
    return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

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
            pending: 0,
        });
        this._queue = Promise.resolve();
        this._scrollTo = false;

        this._onGlobalKeydown = (ev) => this._redirectScannerKey(ev);
        onMounted(() => {
            window.addEventListener("keydown", this._onGlobalKeydown, true);
            this._load();
            this._refreshTimer = setInterval(() => this._refresh(), REFRESH_MS);
        });
        onPatched(() => this._afterPatch());
        onWillUnmount(() => {
            window.removeEventListener("keydown", this._onGlobalKeydown, true);
            clearInterval(this._refreshTimer);
            clearTimeout(this._burstTimer);
            clearTimeout(this._contextTimer);
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

    async _load() {
        if (!this.receptionId) {
            this.state.loading = false;
            this.state.error = "Abre esta pantalla desde una recepción.";
            return;
        }
        try {
            this.state.data = await this.orm.call("rms.reception", "checklist_state", [[this.receptionId]]);
            this.state.error = "";
        } catch (error) {
            this.state.error = this._errorMessage(error);
        }
        this.state.loading = false;
        this._focusInput();
    }

    // Varios operarios a la vez: se refresca lo que han leído los demás.
    async _refresh() {
        if (this.state.pending || this.state.panel || !this.data || document.hidden) {
            return;
        }
        try {
            const data = await this.orm.call("rms.reception", "checklist_state", [[this.receptionId]], {
                context: { bin_size: true },
            });
            if (!this.state.pending) {
                this.state.data = data;
            }
        } catch {
            // Sin red un momento: se reintenta en el siguiente ciclo.
        }
    }

    _errorMessage(error) {
        const data = error && error.data;
        return (data && (data.message || (data.arguments && data.arguments[0]))) || (error && error.message) || "Error";
    }

    // ------------------------------------------------------------------
    // Lectura con la pistola
    // ------------------------------------------------------------------
    _redirectScannerKey(ev) {
        if (this.readonly || this.state.panel || ev.ctrlKey || ev.metaKey || ev.altKey) {
            return;
        }
        const input = this.inputRef.el;
        if (!input || ev.target === input) {
            return;
        }
        const target = ev.target;
        const tag = target && target.tagName;
        if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || (target && target.isContentEditable)) {
            return;
        }
        if (document.querySelector(".modal.show, .o_dialog")) {
            return;
        }
        if (ev.key === "Enter") {
            if (input.value) {
                ev.preventDefault();
                ev.stopPropagation();
                this.addTypedCode();
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
        this.onCodeInput({ target: input });
    }

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
        if (ev.key !== "Enter") {
            return;
        }
        ev.preventDefault();
        this._resetBurst();
        const code = ev.target.value;
        ev.target.value = "";
        this._enqueue(code);
    }

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
        this._focusInput();
    }

    _enqueue(rawCode) {
        const code = (rawCode || "").trim();
        if (!code || this.readonly) {
            return;
        }
        this._unlockAudio();
        const uid = newUid();
        this.state.pending += 1;
        this._queue = this._queue.then(() => this._send(code, uid)).finally(() => {
            this.state.pending -= 1;
        });
        return this._queue;
    }

    async _send(code, uid) {
        const context = this._currentContext();
        try {
            const response = await this.orm.call("rms.reception", "checklist_scan", [[this.receptionId], code], {
                product_id: context ? context.id : false,
                client_uid: uid,
            });
            this._applyScan(response);
        } catch (error) {
            this._setVerdict("error", this._errorMessage(error), code);
            this._beep("red");
        }
    }

    _applyScan(response, options = {}) {
        const result = response.result;
        this.state.data = response.state;
        if (result.sets_context) {
            this._setContext({ id: result.product_id, name: result.product_name });
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

    _currentContext() {
        const context = this.state.context;
        if (context && context.expires < Date.now()) {
            this.state.context = null;
            return null;
        }
        return context;
    }

    _setContext(product) {
        clearTimeout(this._contextTimer);
        if (!product) {
            this.state.context = null;
            return;
        }
        this.state.context = { id: product.id, name: product.name, expires: Date.now() + CONTEXT_TTL_MS };
        this._contextTimer = setTimeout(() => {
            this.state.context = null;
        }, CONTEXT_TTL_MS);
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
    _unlockAudio() {
        try {
            const AudioCtx = window.AudioContext || window.webkitAudioContext;
            if (!this._audio && AudioCtx) {
                this._audio = new AudioCtx();
            }
            if (this._audio && this._audio.state === "suspended") {
                this._audio.resume().catch(() => {});
            }
        } catch {
            // El sonido es opcional.
        }
    }

    _beep(kind) {
        const audio = this._audio;
        if (!audio || audio.state !== "running") {
            return;
        }
        try {
            let start = audio.currentTime;
            for (const [frequency, duration] of TONES[kind] || TONES.grey) {
                const osc = audio.createOscillator();
                const gain = audio.createGain();
                osc.frequency.value = frequency;
                gain.gain.value = 0.15;
                osc.connect(gain);
                gain.connect(audio.destination);
                osc.start(start);
                osc.stop(start + duration);
                start += duration + 0.05;
            }
        } catch {
            // El sonido es opcional.
        }
    }

    // ------------------------------------------------------------------
    // Botones
    // ------------------------------------------------------------------
    async _call(model, method, args, kwargs = {}) {
        try {
            return await this.orm.call(model, method, args, kwargs);
        } catch (error) {
            this.notification.add(this._errorMessage(error), { type: "danger" });
            return null;
        }
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
        if (this.readonly) {
            return;
        }
        const response = await this._call("rms.reception", "checklist_undo", [[this.receptionId]], {
            scan_id: scanId || false,
        });
        if (response) {
            this.state.data = response.state;
            this.state.lastLine = false;
            this.state.verdict = { kind: "grey", title: "Deshecho", message: `Se ha quitado la lectura ${response.undone}.`, code: "" };
        }
        this._focusInput();
    }

    async unreceive(line) {
        const data = await this._call("rms.reception.line", "checklist_unreceive", [[line.id]]);
        if (data) {
            this.state.data = data;
            this.state.openLine = false;
        }
        this._focusInput();
    }

    async changeQty(line, delta) {
        await this.setQty(line, Math.max(0, line.qty_received + delta));
    }

    async onQtyChange(line, ev) {
        const value = parseFloat(String(ev.target.value).replace(",", "."));
        if (Number.isNaN(value)) {
            ev.target.value = this.fmt(line.qty_received);
            return;
        }
        await this.setQty(line, value);
    }

    async setQty(line, quantity) {
        if (this.readonly) {
            return;
        }
        const data = await this._call("rms.reception.line", "checklist_set_qty", [[line.id], quantity]);
        if (data) {
            this.state.data = data;
            this.state.lastLine = line.id;
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
            this.state.data = data;
            this.closePanel();
        }
    }

    async clearDamaged(line) {
        const data = await this._call("rms.reception.line", "checklist_set_damaged", [[line.id]], { damaged: false });
        if (data) {
            this.state.data = data;
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
        this.state.panel = { type: "nolabel", products, productId, serial: "", confirm: "", error: "", print: true };
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
        let response;
        try {
            response = await this.orm.call(
                "rms.reception", "checklist_manual_serial", [[this.receptionId], serial, panel.confirm.trim()],
                { product_id: panel.productId ? Number(panel.productId) : false, print_label: panel.print }
            );
        } catch (error) {
            panel.error = this._errorMessage(error);
            return;
        }
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
                const done = await this._call("rms.reception", "action_finish", [[this.receptionId]]);
                if (done) {
                    this.openForm();
                }
            },
            cancel: () => this._focusInput(),
        });
    }

    openForm() {
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
