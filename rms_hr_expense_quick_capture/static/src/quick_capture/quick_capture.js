/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Component, useRef, useState } from "@odoo/owl";

export class HrExpenseQuickCapture extends Component {
    static template = "rms_hr_expense_quick_capture.QuickCapture";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.fileInputRef = useRef("fileInput");

        this.state = useState({
            phase: "idle", // idle | uploading | done | error
            result: null,
            error: null,
        });
    }

    openCamera() {
        this.fileInputRef.el.click();
    }

    async onFileChange(ev) {
        const file = ev.target.files && ev.target.files[0];
        ev.target.value = "";
        if (!file) {
            return;
        }

        this.state.phase = "uploading";
        this.state.error = null;

        try {
            const image = await this._readFileAsBase64(file);
            const result = await this.orm.call(
                "hr.expense.quick.capture",
                "create_from_photo",
                [image, file.name]
            );
            this.state.result = result;
            this.state.phase = "done";
        } catch (error) {
            this.state.error =
                (error && error.data && error.data.message) ||
                "No se ha podido crear el gasto. Inténtalo de nuevo.";
            this.state.phase = "error";
            console.error(error);
        }
    }

    _readFileAsBase64(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result.split(",")[1]);
            reader.onerror = reject;
            reader.readAsDataURL(file);
        });
    }

    reset() {
        this.state.phase = "idle";
        this.state.result = null;
        this.state.error = null;
    }

    openExpense() {
        if (!this.state.result) {
            return;
        }
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "hr.expense",
            res_id: this.state.result.expense_id,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("actions").add("rms_hr_expense_quick_capture.capture", HrExpenseQuickCapture);
