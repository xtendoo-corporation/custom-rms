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
        // La línea puede no estar guardada todavía (fila nueva, o
        // presupuesto sin guardar): la guardamos automáticamente para no
        // interrumpir el flujo del comercial con "Primero guarde sus
        // cambios".
        if (!this.props.record.resId || this.props.record.dirty) {
            const saved = await this.props.record.save();
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
