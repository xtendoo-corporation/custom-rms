/** @odoo-module **/

import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class SerialSelectorButton extends Component {
    static template = "rms_product_state.SerialSelectorButton";
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
    }

    get count() {
        return this.props.record.data.serial_count || 0;
    }

    get label() {
        const stateName = this.props.record.data.serial_state_name;
        return stateName || "Nuevo";
    }

    async onClick(ev) {
        ev.stopPropagation();
        // Protección contra doble disparo del propio click.
        if (this.isHandlingClick) {
            return;
        }
        this.isHandlingClick = true;
        try {
            const rootRecord = this.props.record.model.root;
            const wasUnsaved = !rootRecord.resId || rootRecord.dirty;
            if (wasUnsaved) {
                // La línea es una fila de un one2many (order_line) dentro
                // del presupuesto: guardar solo la línea falla si el
                // propio presupuesto (su registro raíz) tampoco está
                // guardado todavía, porque a la línea le faltaría
                // order_id. Por eso guardamos siempre el registro raíz.
                const saved = await rootRecord.save();
                if (saved === false) {
                    // Guardado bloqueado (p. ej. falta un campo
                    // obligatorio): el formulario ya muestra el error de
                    // validación.
                    return;
                }
                // Justo tras guardar un pedido nuevo, el id real de esta
                // línea tarda en reflejarse de forma fiable en el
                // cliente (probado con varias estrategias: esperar un
                // tick, recargar la línea, recargar el pedido, buscar la
                // línea fresca en el pedido raíz, y hasta consultar el
                // servidor directamente — ninguna es consistente al
                // 100%). En vez de arriesgarnos a abrir el wizard sobre
                // un id equivocado o a fallar en silencio, pedimos un
                // segundo click: con el pedido ya guardado, el resId de
                // la línea SÍ está siempre disponible de forma fiable.
                this.notification.add(
                    "Presupuesto guardado. Pulsa de nuevo el botón de la línea para elegir las series.",
                    { type: "info" }
                );
                return;
            }
            if (!this.props.record.resId) {
                return;
            }
            const action = await this.orm.call(
                "sale.order.line",
                "action_open_serial_selector",
                [this.props.record.resId]
            );
            this.action.doAction(action, {
                // Recargamos el registro raíz (el pedido), no solo la
                // línea: el wizard cambia price_unit/discount de la línea,
                // y eso cambia los totales del pedido (Importe base,
                // Total...), que viven en el registro padre y no se
                // refrescan solos.
                onClose: () => rootRecord.load(),
            });
        } finally {
            this.isHandlingClick = false;
        }
    }
}

registry.category("fields").add("serial_selector_button", {
    component: SerialSelectorButton,
});
