/** @odoo-module **/

import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component } from "@odoo/owl";

export class SerialAvailabilityPicker extends Component {
    static template = "rms_product_state.SerialAvailabilityPicker";
    static props = { ...standardFieldProps };

    get candidates() {
        return this.props.record.data.lot_candidates || [];
    }

    get selectedIds() {
        const field = this.props.record.data[this.props.name];
        return field.currentIds || field.resIds || [];
    }

    isSelected(id) {
        return this.selectedIds.includes(id);
    }

    async toggle(candidate) {
        if (candidate.reserved_by) {
            return;
        }
        const current = this.selectedIds;
        const next = this.isSelected(candidate.id)
            ? current.filter((id) => id !== candidate.id)
            : [...current, candidate.id];
        await this.props.record.update({ [this.props.name]: [[6, 0, next]] });
    }
}

registry.category("fields").add("serial_availability_picker", {
    component: SerialAvailabilityPicker,
});
