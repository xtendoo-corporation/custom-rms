/** @odoo-module **/

import { registry } from "@web/core/registry";
import { BinaryField, binaryField } from "@web/views/fields/binary/binary_field";

export class KnowledgeBinaryField extends BinaryField {
    static template = "rms_custom_knowledge.KnowledgeBinaryField";
}

export const knowledgeBinaryField = {
    ...binaryField,
    component: KnowledgeBinaryField,
};

registry.category("fields").add("knowledge_binary", knowledgeBinaryField);
