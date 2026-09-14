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
        const count = this.count;
        if (!count) {
            return "2ª Mano / Ex-Demo";
        }
        return count === 1 ? "1 serie" : `${count} series`;
    }

    async onClick(ev) {
        ev.stopPropagation();
        // La línea es una fila de un one2many (order_line) dentro del
        // presupuesto: guardar solo la línea falla si el propio presupuesto
        // (su registro raíz) tampoco está guardado todavía, porque a la
        // línea le faltaría order_id. Por eso guardamos siempre el
        // registro raíz del formulario, no la línea suelta — así no
        // interrumpimos al comercial con "Primero guarde sus cambios".
        const rootRecord = this.props.record.model.root;
        if (!rootRecord.resId || rootRecord.dirty) {
            const saved = await rootRecord.save();
            if (saved === false) {
                // Guardado bloqueado (p. ej. falta un campo obligatorio):
                // el formulario ya muestra el error de validación.
                return;
            }
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
            onClose: () => this.props.record.load(),
        });
    }
}

registry.category("fields").add("serial_selector_button", {
    component: SerialSelectorButton,
});
