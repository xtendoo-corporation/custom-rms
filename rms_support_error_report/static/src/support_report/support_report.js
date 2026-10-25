/** @odoo-module **/

import { browser } from "@web/core/browser/browser";
import { ErrorDialog, WarningDialog } from "@web/core/errors/error_dialogs";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { useState } from "@odoo/owl";

/**
 * Añade "Notificar a soporte" a las ventanas de error de Odoo:
 * - ErrorDialog (y sus hijas RPCErrorDialog, ClientErrorDialog...): fallos
 *   de código, el típico "Oops! Something went wrong".
 * - WarningDialog: UserError / ValidationError / AccessError, como el de
 *   "una empresa no puede seguir dos veces el mismo objeto".
 *
 * Solo recoge datos que ya están en la ventana (mensaje, traceback que el
 * servidor manda en data.debug) más la pantalla donde se estaba; el resto
 * (informe de IA, aviso en Conversaciones) lo hace el servidor.
 */
function sanitizedUrl() {
    const url = new URL(browser.location.href);
    const allowed = new Set(["model", "id", "action", "view_type", "menu_id"]);
    for (const key of [...url.searchParams.keys()]) {
        if (!allowed.has(key)) url.searchParams.delete(key);
    }
    const fragment = new URLSearchParams(url.hash.slice(1));
    for (const key of [...fragment.keys()]) {
        if (!allowed.has(key)) fragment.delete(key);
    }
    url.hash = fragment.toString();
    url.username = "";
    url.password = "";
    return url.href;
}

function useSupportReport(dialog) {
    const orm = useService("orm");
    const state = useState({
        step: "idle", // idle | form | sending | sent | error
        comment: "",
        result: "",
    });

    function collectPayload() {
        const props = dialog.props;
        const serverTraceback = (props.data && props.data.debug) || "";
        let traceback = dialog.traceback || props.traceback || "";
        if (serverTraceback && !traceback.includes(serverTraceback)) {
            traceback = `${serverTraceback}\n${traceback}`;
        }
        const payload = {
            error_type: props.exceptionName || props.name || dialog.title || "",
            error_message: dialog.message || props.message || "",
            traceback,
            user_comment: state.comment,
            url: sanitizedUrl(),
            res_model: props.model || "",
            res_id: props.id || 0,
        };
        try {
            const controller = dialog.env.services.action.currentController;
            const controllerProps = (controller && controller.props) || {};
            payload.res_model = payload.res_model || controllerProps.resModel || "";
            payload.res_id = payload.res_id || controllerProps.resId || 0;
        } catch {
            // Sin acción activa (p. ej. error al arrancar): no pasa nada.
        }
        return payload;
    }

    return {
        state,
        open() {
            state.step = "form";
        },
        async send() {
            state.step = "sending";
            try {
                const result = await orm.call("rms.support.ticket", "report_error", [
                    collectPayload(),
                ]);
                state.result = result.message;
                state.step = result.status === "rate_limited" ? "error" : "sent";
            } catch {
                state.result =
                    "No se ha podido enviar el aviso a soporte. Copia el error y avisa por otra vía.";
                state.step = "error";
            }
        },
    };
}

patch(ErrorDialog.prototype, {
    setup() {
        super.setup(...arguments);
        this.supportReport = useSupportReport(this);
    },
});

patch(WarningDialog.prototype, {
    setup() {
        super.setup(...arguments);
        this.supportReport = useSupportReport(this);
    },
});
