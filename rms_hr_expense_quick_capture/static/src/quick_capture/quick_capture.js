/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Component, useRef, useState } from "@odoo/owl";

// Una foto de una cámara moderna puede pesar varios MB; con poca cobertura
// móvil eso puede tardar más de un minuto en subirse. Un ticket es texto:
// no hace falta resolución completa para que la IA lo lea bien, así que se
// reduce/comprime en el propio móvil antes de subirla.
const MAX_IMAGE_DIMENSION = 1800;
const IMAGE_QUALITY = 0.8;

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
            const { image, filename } = await this._compressImage(file);
            const result = await this.orm.call(
                "hr.expense.quick.capture",
                "create_from_photo",
                [image, filename]
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

    _readFileAsDataUrl(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result);
            reader.onerror = reject;
            reader.readAsDataURL(file);
        });
    }

    _loadImage(dataUrl) {
        return new Promise((resolve, reject) => {
            const img = new Image();
            img.onload = () => resolve(img);
            img.onerror = reject;
            img.src = dataUrl;
        });
    }

    async _compressImage(file) {
        let dataUrl;
        try {
            dataUrl = await this._readFileAsDataUrl(file);
            const img = await this._loadImage(dataUrl);

            let { width, height } = img;
            if (width > MAX_IMAGE_DIMENSION || height > MAX_IMAGE_DIMENSION) {
                if (width >= height) {
                    height = Math.round((height * MAX_IMAGE_DIMENSION) / width);
                    width = MAX_IMAGE_DIMENSION;
                } else {
                    width = Math.round((width * MAX_IMAGE_DIMENSION) / height);
                    height = MAX_IMAGE_DIMENSION;
                }
            }

            const canvas = document.createElement("canvas");
            canvas.width = width;
            canvas.height = height;
            const ctx = canvas.getContext("2d");
            ctx.drawImage(img, 0, 0, width, height);

            const compressed = canvas.toDataURL("image/jpeg", IMAGE_QUALITY);
            return {
                image: compressed.split(",")[1],
                filename: (file.name || "ticket").replace(/\.\w+$/, "") + ".jpg",
            };
        } catch (error) {
            // Si por lo que sea no se puede comprimir (formato raro,
            // navegador antiguo...), se sube la foto original tal cual en
            // vez de fallar del todo.
            console.error("No se pudo comprimir la imagen, se sube el original", error);
            dataUrl = dataUrl || (await this._readFileAsDataUrl(file));
            return { image: dataUrl.split(",")[1], filename: file.name || "ticket.jpg" };
        }
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
