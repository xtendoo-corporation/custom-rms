/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import {
    X2ManyField,
    x2ManyField,
} from "@web/views/fields/x2many/x2many_field";

export class KnowledgeSubdirectoryOne2Many extends X2ManyField {
    setup() {
        super.setup(...arguments);
        this.orm = useService("orm");
    }

    async onAdd() {
        const saved = await this.props.record.save();
        const parentId = this.props.record.resId;
        if (!saved || !parentId) {
            this.notificationService.add(
                "Guarda primero el directorio actual para añadir una carpeta.",
                { type: "warning" }
            );
            return;
        }

        const action = await this.orm.call(
            "document.knowledge.category",
            "action_create_knowledge_subdirectory",
            [[parentId]]
        );
        return this.action.doAction(action, {
            onClose: async () => {
                await this.props.record.load();
            },
        });
    }
}

export const knowledgeSubdirectoryOne2Many = {
    ...x2ManyField,
    component: KnowledgeSubdirectoryOne2Many,
};

registry
    .category("fields")
    .add("knowledge_subdirectory_one2many", knowledgeSubdirectoryOne2Many);
