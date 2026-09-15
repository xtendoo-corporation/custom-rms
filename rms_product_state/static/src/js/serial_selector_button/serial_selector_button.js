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
        // Protección contra doble disparo: el guardado del registro raíz
        // puede provocar un re-render de este botón mientras el primer
        // click todavía se está procesando, y sin esta guarda se han visto
        // varias llamadas a action_open_serial_selector desde un único
        // click de usuario (varios diálogos pisándose y errores de cliente).
        if (this.isHandlingClick) {
            return;
        }
        this.isHandlingClick = true;
        try {
            // La línea es una fila de un one2many (order_line) dentro del
            // presupuesto: guardar solo la línea falla si el propio
            // presupuesto (su registro raíz) tampoco está guardado
            // todavía, porque a la línea le faltaría order_id. Por eso
            // guardamos siempre el registro raíz del formulario, no la
            // línea suelta — así no interrumpimos al comercial con
            // "Primero guarde sus cambios".
            const rootRecord = this.props.record.model.root;
            // Guardamos el "id local" (estable, propio del datapoint del
            // framework) ANTES de guardar: this.props.record puede quedar
            // apuntando a un objeto obsoleto una vez el pedido nuevo se
            // guarda (el resId de esa referencia nunca llega a
            // actualizarse, aunque se espere), así que tras guardar
            // buscamos la línea fresca en el registro raíz por este id en
            // vez de confiar en that stale this.props.record.
            const localId = this.props.record.id;
            if (!rootRecord.resId || rootRecord.dirty) {
                const saved = await rootRecord.save();
                if (saved === false) {
                    // Guardado bloqueado (p. ej. falta un campo
                    // obligatorio): el formulario ya muestra el error de
                    // validación.
                    return;
                }
            }
            const lineRecords = (rootRecord.data.order_line && rootRecord.data.order_line.records) || [];
            const freshLine = lineRecords.find((r) => r.id === localId) || this.props.record;
            if (!freshLine.resId) {
                return;
            }
            const action = await this.orm.call(
                "sale.order.line",
                "action_open_serial_selector",
                [freshLine.resId]
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
