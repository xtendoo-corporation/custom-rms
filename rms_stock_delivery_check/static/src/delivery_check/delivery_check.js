/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { Component, onMounted, onWillUnmount, useRef, useState } from "@odoo/owl";

// La pistola Honeywell no manda Enter: "teclea" el código entero en pocos
// milisegundos. Una ráfaga rápida seguida de una pausa es una lectura.
// (Mismos valores probados en el escáner del recuento.)
const BURST_GAP_MS = 45;
const BURST_PAUSE_MS = 160;
const BURST_MIN_CHARS = 4;
const REFRESH_MS = 5000;
const FRAME_ID = "o_rms_dc_label_frame";

function isIOS() {
    const ua = navigator.userAgent || "";
    return /iPad|iPhone|iPod/.test(ua) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
}

/** Etiqueta 50x29: cuadro de impresión directo; en el iPad, pestaña nueva. */
function printLabelUrl(url) {
    if (isIOS()) {
        window.open(url, "_blank");
        return;
    }
    document.getElementById(FRAME_ID)?.remove();
    const frame = document.createElement("iframe");
    frame.id = FRAME_ID;
    frame.setAttribute("aria-hidden", "true");
    frame.style.cssText = "position:fixed;right:0;bottom:0;width:1px;height:1px;border:0;opacity:0;pointer-events:none;";
    let done = false;
    frame.onload = () => {
        if (done) {
            return;
        }
        done = true;
        setTimeout(() => {
            try {
                frame.contentWindow.focus();
                frame.contentWindow.print();
            } catch {
                window.open(url, "_blank");
            }
        }, 500);
    };
    frame.src = url;
    document.body.appendChild(frame);
}

const ICONS = { ok: "fa-check", amber: "fa-exclamation-triangle", red: "fa-ban", grey: "fa-barcode", duplicate: "fa-clone" };

export class DeliveryCheck extends Component {
    static template = "rms_stock_delivery_check.DeliveryCheck";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.dialog = useService("dialog");
        this.inputRef = useRef("codeInput");
        const action = this.props.action || {};
        this.pickingId = (action.params && action.params.picking_id) || (action.context && action.context.active_id);
        this.state = useState({
            data: null,
            loading: true,
            busy: false,
            error: "",
            banner: null, // última lectura hecha en ESTE aparato
            lastScanId: 0,
        });
        this._queue = [];
        this._working = false;
        this._burst = null;
        this._onGlobalKeydown = (ev) => this._redirectScannerKey(ev);

        onMounted(async () => {
            window.addEventListener("keydown", this._onGlobalKeydown, true);
            await this._load();
            this._focusInput();
            // Varios operarios a la vez: se refresca solo.
            this._refreshTimer = setInterval(() => {
                if (!this._working && !this.state.busy && !document.hidden) {
                    this._load(true);
                }
            }, REFRESH_MS);
        });
        onWillUnmount(() => {
            window.removeEventListener("keydown", this._onGlobalKeydown, true);
            clearInterval(this._refreshTimer);
            clearTimeout(this._burstTimer);
        });
    }

    // ------------------------------------------------------------ servidor
    async _rpc(method, args = []) {
        try {
            this.state.error = "";
            return await this.orm.call("stock.picking", method, [[this.pickingId], ...args]);
        } catch (error) {
            const message = (error && error.data && error.data.message) || (error && error.message) || String(error);
            this.state.error = message;
            this._beep(false);
            return null;
        }
    }

    async _load(silent = false) {
        if (!this.pickingId) {
            this.state.loading = false;
            this.state.error = "No se sabe qué albarán abrir. Vuelve al albarán y pulsa «Abrir checklist».";
            return;
        }
        let data = null;
        try {
            data = await this.orm.call("stock.picking", "rms_check_get_state", [[this.pickingId]]);
        } catch (error) {
            if (!silent) {
                this.state.error = (error && error.data && error.data.message) || "No se ha podido cargar el albarán.";
            }
        }
        if (data && !this._working) {
            this.state.data = data;
        }
        this.state.loading = false;
    }

    async _do(method, args = []) {
        if (this.state.busy) {
            return null;
        }
        this.state.busy = true;
        const result = await this._rpc(method, args);
        this.state.busy = false;
        if (result) {
            this.state.data = result.state || result;
        }
        this._focusInput();
        return result;
    }

    // ------------------------------------------------------------- pistola
    get canScan() {
        return Boolean(this.state.data && this.state.data.editable);
    }

    _focusInput() {
        const input = this.inputRef.el;
        if (input && this.canScan && !document.querySelector(".modal.show, .o_dialog")) {
            input.focus({ preventScroll: true });
        }
    }

    _redirectScannerKey(ev) {
        if (!this.canScan || ev.ctrlKey || ev.metaKey || ev.altKey || ev.isComposing) {
            return;
        }
        const input = this.inputRef.el;
        const target = ev.target;
        if (!input || target === input) {
            return;
        }
        if (target && target.closest && target.closest("input, textarea, select, [contenteditable='true'], .modal")) {
            return;
        }
        if (document.querySelector(".modal.show, .o_dialog")) {
            return;
        }
        if (ev.key === "Enter") {
            if (input.value) {
                ev.preventDefault();
                ev.stopPropagation();
                this._submitInput();
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
        this.onCodeInput({ target: input });
    }

    onCodeKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this._submitInput();
        }
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

    _submitInput() {
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

    addTypedCode() {
        this._submitInput();
    }

    _enqueue(code) {
        code = (code || "").trim();
        if (!code) {
            return;
        }
        this._queue.push(code);
        this._processQueue();
    }

    async _processQueue() {
        if (this._working) {
            return;
        }
        this._working = true;
        while (this._queue.length) {
            const code = this._queue.shift();
            const result = await this._rpc("rms_check_scan", [code]);
            if (!result) {
                this.state.banner = { result: "red", code, label: "No se ha guardado la lectura", message: this.state.error };
                continue;
            }
            this.state.data = result.state;
            const scan = result.state.feed.find((row) => row.id === result.scan_id);
            if (scan) {
                this.state.lastScanId = scan.id;
                this.state.banner = scan;
                this._beep(scan.result === "ok");
            }
        }
        this._working = false;
    }

    _beep(ok) {
        try {
            const Ctx = window.AudioContext || window.webkitAudioContext;
            if (!Ctx) {
                return;
            }
            this._audio = this._audio || new Ctx();
            const osc = this._audio.createOscillator();
            const gain = this._audio.createGain();
            osc.frequency.value = ok ? 880 : 220;
            gain.gain.value = 0.08;
            osc.connect(gain);
            gain.connect(this._audio.destination);
            osc.start();
            osc.stop(this._audio.currentTime + (ok ? 0.08 : 0.3));
        } catch {
            // sin sonido
        }
    }

    // ------------------------------------------------------------- acciones
    icon(result) {
        return ICONS[result] || "fa-question";
    }

    fmt(value) {
        return Number.isInteger(value) ? String(value) : String(Math.round(value * 100) / 100);
    }

    missing(group) {
        return Math.max(group.demand - group.done, 0);
    }

    pendingUnits(group) {
        return group.units.filter((unit) => unit.result === "amber" && unit.approval === "pending").length;
    }

    get statusText() {
        const data = this.state.data;
        const counters = data.counters;
        switch (data.picking.check_state) {
            case "pending_admin":
                return data.is_manager
                    ? "Pendiente de tu decisión: aprueba o rechaza lo que está en ámbar y decide si sale incompleto."
                    : "Pendiente de administrador. Avisa al responsable: él decide lo que está en ámbar o lo que falta.";
            case "ready":
                return counters.missing
                    ? "El administrador ha autorizado la salida incompleta. Ya se puede validar."
                    : "Todo correcto. Ya se puede validar el albarán.";
            case "done":
                return "Albarán validado con los nº de serie leídos.";
            default:
                if (!counters.missing && !counters.amber && !counters.unreviewed) {
                    return "Todo leído. Pulsa «He terminado».";
                }
                return "Lee con la pistola el nº de serie de cada caja.";
        }
    }

    undo(scanId) {
        return this._do("rms_check_undo", [scanId]);
    }

    toggleReviewed(unit) {
        return this._do("rms_check_set_reviewed", [unit.scan_id, !unit.reviewed]);
    }

    setQty(group, qty) {
        qty = Math.max(0, Math.min(group.demand, qty));
        return this._do("rms_check_set_qty", [group.move_id, qty]);
    }

    onQtyChange(group, ev) {
        const value = parseFloat(String(ev.target.value).replace(",", "."));
        return this.setQty(group, Number.isFinite(value) ? value : 0);
    }

    printLabel(lotId) {
        if (lotId) {
            printLabelUrl(`/report/pdf/${this.state.data.label_report}/${lotId}`);
        }
    }

    async finish() {
        const result = await this._do("rms_check_finish");
        if (result) {
            this.state.banner = null;
        }
    }

    reopen() {
        return this._do("rms_check_reopen");
    }

    _confirm(title, body, confirmLabel, callback) {
        this.dialog.add(
            ConfirmationDialog,
            { title, body, confirmLabel, cancelLabel: "Cancelar", confirm: callback, cancel: () => {} },
            { onClose: () => this._focusInput() }
        );
    }

    validate() {
        const data = this.state.data;
        const body = data.counters.missing
            ? `Sale INCOMPLETO: ${this.fmt(data.counters.read)} de ${this.fmt(data.counters.total)} unidades (autorizado por el administrador). ¿Validar el albarán?`
            : `Salen ${this.fmt(data.counters.read)} unidades, todas leídas. ¿Validar el albarán?`;
        this._confirm("Validar albarán", body, "Validar", () => this._do("rms_check_validate"));
    }

    approve(unit) {
        const extra = unit.reason === "pack_incomplete" ? " Esto ROMPE el paquete y queda constancia de que lo decides tú." : "";
        this._confirm(
            "Aprobar",
            `${unit.serial}: ${unit.message}${extra} ¿Aprobar que salga?`,
            "Aprobar que salga",
            () => this._do("rms_check_approve", [unit.scan_id])
        );
    }

    reject(unit) {
        this._confirm("Rechazar", `${unit.serial}: ${unit.message} ¿Rechazar? Este equipo NO saldrá.`, "No sale", () =>
            this._do("rms_check_reject", [unit.scan_id])
        );
    }

    decidePartial(decision) {
        const body =
            decision === "backorder"
                ? "Sale lo leído y lo que falta queda PENDIENTE en otro albarán. ¿Seguro?"
                : "Sale lo leído y lo que falta NO queda pendiente (no se enviará). ¿Seguro?";
        this._confirm("Envío parcial", body, "Sí, autorizar", () => this._do("rms_check_decide_partial", [decision]));
    }

    printSerials() {
        window.open(`/report/pdf/rms_stock_delivery_check.report_delivery_serials/${this.pickingId}`, "_blank");
    }

    back() {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "stock.picking",
            res_id: this.pickingId,
            views: [[false, "form"]],
            target: "current",
        }, { clearBreadcrumbs: false });
    }
}

registry.category("actions").add("rms_stock_delivery_check.checklist", DeliveryCheck);
