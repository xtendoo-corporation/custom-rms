/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Component, onMounted, useRef, useState } from "@odoo/owl";

export class AiHelpAssistant extends Component {
    static template = "rms_ai_help_assistant.AiHelpAssistant";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.messagesRef = useRef("messages");

        this.state = useState({
            messages: [
                {
                    role: "assistant",
                    text:
                        "Hola, soy el asistente de Odoo de RMS-Proaudio. Puedo explicarte " +
                        "cómo hacer algo (crear un cliente, asignar una lista de precios...) " +
                        "o consultarte un dato real (precio, stock, un pedido...). " +
                        "No puedo crear ni modificar nada, solo informarte.",
                    synthetic: true,
                },
            ],
            draft: "",
            loading: false,
        });

        onMounted(() => this.scrollToBottom());
    }

    scrollToBottom() {
        const el = this.messagesRef.el;
        if (el) {
            el.scrollTop = el.scrollHeight;
        }
    }

    onInput(ev) {
        this.state.draft = ev.target.value;
    }

    onKeydown(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.sendMessage();
        }
    }

    get transcript() {
        return this.state.messages
            .filter((m) => !m.synthetic)
            .map((m) => ({ role: m.role, text: m.text }));
    }

    async sendMessage() {
        const text = this.state.draft.trim();
        if (!text || this.state.loading) {
            return;
        }
        this.state.messages.push({ role: "user", text });
        this.state.draft = "";
        this.state.loading = true;
        this.scrollToBottom();

        try {
            const result = await this.orm.call(
                "rms.ai.help.assistant",
                "send_message",
                [this.transcript]
            );
            this.state.messages.push({
                role: "assistant",
                text: result.text,
                isError: result.type === "error",
            });
        } catch (error) {
            this.state.messages.push({
                role: "assistant",
                text: "Ha ocurrido un error inesperado. Inténtalo de nuevo.",
                isError: true,
            });
            console.error(error);
        } finally {
            this.state.loading = false;
            this.scrollToBottom();
        }
    }
}

registry.category("actions").add("rms_ai_help_assistant.chat", AiHelpAssistant);
