/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Component, onMounted, useRef, useState } from "@odoo/owl";

export class AiQuoteAssistant extends Component {
    static template = "rms_ai_quote_assistant.AiQuoteAssistant";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.messagesRef = useRef("messages");

        const context = this.props.action?.context || {};
        this.pinnedOpportunityId = context.default_opportunity_id || null;
        this.pinnedOpportunityName = context.default_opportunity_name || null;

        const greeting = this.pinnedOpportunityId
            ? `Hola, este presupuesto se vinculará a la oportunidad "${this.pinnedOpportunityName}". ` +
              "Dime con qué productos quieres hacerlo (p. ej. \"3 X40 y una Quantum 3\")."
            : "Hola, dime a qué cliente y con qué productos quieres " +
              "hacer un presupuesto (p. ej. \"hazle un presupuesto a " +
              "fulanito con 3 X40 y una Quantum 3\").";

        this.state = useState({
            messages: [{ role: "assistant", text: greeting, synthetic: true }],
            draft: "",
            loading: false,
            proposal: null,
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
        this.state.proposal = null;
        this.state.loading = true;
        this.scrollToBottom();

        try {
            const result = await this.orm.call(
                "rms.ai.quote.assistant",
                "send_message",
                [this.transcript, this.pinnedOpportunityId]
            );
            this.handleResult(result);
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

    handleResult(result) {
        this.state.messages.push({
            role: "assistant",
            text: result.text,
            isError: result.type === "error",
        });
        if (result.type === "proposal") {
            this.state.proposal = {
                partner_id: result.partner_id,
                lines: result.lines,
                // When pinned, the opportunity is fixed and no selector is
                // shown; otherwise the user picks one of the partner's open
                // opportunities, none, or types a name for a new one.
                opportunities: this.pinnedOpportunityId ? null : (result.opportunities || []),
                opportunitySelection: "",
                newOpportunityName: "",
            };
        }
    }

    onOpportunitySelectionChange(ev) {
        if (this.state.proposal) {
            this.state.proposal.opportunitySelection = ev.target.value;
        }
    }

    onNewOpportunityNameInput(ev) {
        if (this.state.proposal) {
            this.state.proposal.newOpportunityName = ev.target.value;
        }
    }

    async confirmProposal() {
        if (!this.state.proposal || this.state.loading) {
            return;
        }
        const { partner_id, lines, opportunitySelection, newOpportunityName } = this.state.proposal;
        let opportunityId = this.pinnedOpportunityId || null;
        let newOpportunityNameArg = null;
        if (!this.pinnedOpportunityId) {
            if (opportunitySelection === "__new__") {
                newOpportunityNameArg = (newOpportunityName || "").trim() || null;
            } else if (opportunitySelection) {
                opportunityId = parseInt(opportunitySelection, 10);
            }
        }
        this.state.loading = true;
        this.state.proposal = null;
        try {
            const result = await this.orm.call(
                "rms.ai.quote.assistant",
                "confirm_quote",
                [partner_id, lines, opportunityId, newOpportunityNameArg]
            );
            this.handleResult(result);
        } catch (error) {
            this.state.messages.push({
                role: "assistant",
                text: "Ha ocurrido un error inesperado al crear el presupuesto.",
                isError: true,
            });
            console.error(error);
        } finally {
            this.state.loading = false;
            this.scrollToBottom();
        }
    }

    cancelProposal() {
        this.state.proposal = null;
        this.state.messages.push({
            role: "assistant",
            text: "Presupuesto cancelado.",
            synthetic: true,
        });
        this.scrollToBottom();
    }
}

registry.category("actions").add("rms_ai_quote_assistant.chat", AiQuoteAssistant);
