/** @odoo-module **/

import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { Component, onMounted, onWillUnmount, useRef, useState } from "@odoo/owl";
import {
    BurstReader, QtyWriter, ScanAudio, ScanQueue, actionErrorText, callAction, errorKind, sendRpc,
} from "@rms_scan_queue/scan_queue";

// La cola de lecturas (una lectura nunca se pierde en silencio), el corte de
// ráfagas de la pistola sin Enter y el sonido son comunes a las pantallas de
// pistola: rms_scan_queue.
const REFRESH_MS = 5000;
const TONE_OK = [[880, 0.08]];
const TONE_BAD = [[220, 0.3]];
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
        this.notification = useService("notification");
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
        this._generation = 0; // sube con cada respuesta aplicada: un refresco viejo no pisa lo nuevo

        // Cola de lecturas de ESTE albarán, operario y aparato.
        this.queueState = useState(ScanQueue.initialState());
        this.queue = new ScanQueue({
            state: this.queueState,
            name: `delivery.${this.pickingId}.u${user.userId}`,
            dialog: this.dialog,
            notification: this.notification,
            where: "en el albarán",
            // Se envían en orden y de una en una (paquetes, unidades leídas).
            send: (item) => sendRpc("stock.picking", "rms_check_scan", [[this.pickingId], item.code],
                { client_uid: item.uid }),
            reject: (item, result) => (result && result.scan_id ? false
                : "Lectura vacía: no es un código que se pueda guardar."),
            onSaved: (item, result) => this._applyScan(result),
            onAside: (item, message) => {
                this.state.banner = { result: "red", code: item.code, label: "No se ha guardado la lectura", message };
                this._beep(false);
            },
            probe: () => this._load(true),
            afterAction: () => this._focusInput(),
        });
        this.reader = new BurstReader({
            state: this.queueState,
            getInput: () => this.inputRef.el,
            onCode: (code) => this._enqueue(code),
        });
        this.audio = new ScanAudio(this.queueState);
        this.qtyWriter = new QtyWriter({
            send: (moveId, qty) => callAction(this.queue, "stock.picking", "rms_check_set_qty", [[this.pickingId], moveId, qty]),
            onSaved: (moveId, qty, data, isLast) => {
                if (isLast) {
                    this._setData(data);
                }
            },
            onFailed: (moveId, confirmed, message) => {
                this._showQty(moveId, confirmed);
                this.state.error = message;
                this._beep(false);
            },
        });
        this._onGlobalKeydown = (ev) => {
            if (this.canScan) {
                this.reader.redirectKey(ev);
            }
        };

        onMounted(async () => {
            window.addEventListener("keydown", this._onGlobalKeydown, true);
            this.audio.start();
            if (this.pickingId) {
                // Lo que quedó sin enviar en este aparato se ve (y se envía) desde ya.
                this.queue.start();
            }
            await this._load();
            this._focusInput();
            // Varios operarios a la vez: se refresca solo.
            this._refreshTimer = setInterval(() => {
                if (!this.state.busy && !document.hidden) {
                    this._load(true);
                }
            }, REFRESH_MS);
        });
        onWillUnmount(() => {
            window.removeEventListener("keydown", this._onGlobalKeydown, true);
            clearInterval(this._refreshTimer);
            this.queue.destroy();
            this.reader.destroy();
            this.audio.destroy();
        });
    }

    // ------------------------------------------------------------ servidor
    _setData(data) {
        this._generation += 1;
        this.state.data = data;
    }

    // Con lecturas pendientes no se refresca: la cola trae el estado al entrar.
    async _load(silent = false) {
        if (!this.pickingId) {
            this.state.loading = false;
            this.state.error = "No se sabe qué albarán abrir. Vuelve al albarán y pulsa «Abrir checklist».";
            return;
        }
        if (silent && (this.queueState.pending.length || this.qtyWriter.busy)) {
            return;
        }
        const generation = this._generation;
        try {
            const data = await sendRpc("stock.picking", "rms_check_get_state", [[this.pickingId]]);
            this.queue.noteOk();
            if (generation === this._generation && !this.queueState.pending.length && !this.qtyWriter.busy) {
                this.state.data = data;
                if (this._loadFailed) {
                    this._loadFailed = false;
                    this.state.error = "";
                }
            }
        } catch (error) {
            const kind = await errorKind(error);
            this.queue.noteError(kind);
            if (!this.state.data) {
                this._loadFailed = true;
                this.state.error = kind === "user" ? actionErrorText(error, kind)
                    : "No se ha podido cargar el albarán: no hay conexión. Se vuelve a intentar sola.";
            }
        }
        this.state.loading = false;
    }

    // Botones que no son lecturas (He terminado, validar, aprobar, Revisado,
    // deshacer): NO van a la cola. La llamada siempre termina y, si falla, se
    // dice claro y el botón queda libre para volver a pulsar.
    async _do(method, args = []) {
        if (this.state.busy) {
            return null;
        }
        this.state.busy = true;
        this.state.error = "";
        const answer = await callAction(this.queue, "stock.picking", method, [[this.pickingId], ...args]);
        this.state.busy = false;
        let result = null;
        if (answer.ok) {
            result = answer.result;
            if (result) {
                this._setData(result.state || result);
            }
        } else {
            this.state.error = answer.message;
            this._beep(false);
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
    _enqueue(code) {
        code = (code || "").trim();
        if (!code) {
            return;
        }
        this.queue.enqueue(code);
        if (this.queueState.conn !== "ok") {
            this.state.banner = { result: "grey", code, label: "Pendiente de enviar",
                message: "Guardada en este dispositivo: se enviará sola al volver la conexión." };
        }
    }

    _applyScan(result) {
        this._setData(result.state);
        const scan = result.scan || result.state.feed.find((row) => row.id === result.scan_id);
        if (scan) {
            this.state.lastScanId = scan.id;
            this.state.banner = scan;
            this._beep(scan.result === "ok");
        }
    }

    _beep(ok) {
        this.audio.play(ok ? TONE_OK : TONE_BAD);
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

    // + y −: se envía la cantidad FINAL (no "+1"), de una en una. Un doble
    // toque o un reenvío no cuentan dos veces; si falla, vuelve a lo guardado.
    setQty(group, qty) {
        qty = Math.max(0, Math.min(group.demand, qty));
        const confirmed = group.done;
        this.state.error = "";
        this._showQty(group.move_id, qty);
        this.qtyWriter.set(group.move_id, qty, confirmed);
    }

    _showQty(moveId, qty) {
        const group = this.state.data.groups.find((row) => row.move_id === moveId);
        if (group) {
            group.done = qty;
            group.complete = qty >= group.demand;
        }
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
        // Con lecturas sin enviar o con error no se termina: se quedarían fuera.
        if (this.queue.blocked("terminar") || this._qtyPending()) {
            return;
        }
        const result = await this._do("rms_check_finish");
        if (result) {
            this.state.banner = null;
        }
    }

    reopen() {
        return this._do("rms_check_reopen");
    }

    _qtyPending() {
        if (this.qtyWriter.busy) {
            this.notification.add("Se está guardando una cantidad: espera un momento y vuelve a pulsar.",
                { type: "warning" });
            return true;
        }
        return false;
    }

    _confirm(title, body, confirmLabel, callback) {
        this.dialog.add(
            ConfirmationDialog,
            { title, body, confirmLabel, cancelLabel: "Cancelar", confirm: callback, cancel: () => {} },
            { onClose: () => this._focusInput() }
        );
    }

    validate() {
        if (this.queue.blocked("validar")) {
            return;
        }
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
        if (this.canScan && this.queue.blocked("salir")) {
            return;
        }
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
