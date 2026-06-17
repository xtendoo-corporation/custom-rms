from copy import deepcopy

from odoo import api, models


class ResGroups(models.Model):
    _inherit = 'res.groups'

    @api.model
    def _rms_hidden_user_form_group_xmlids(self):
        return (
            'rms_custom_knowledge.group_knowledge_manager',
            'rms_custom_knowledge.group_knowledge_contributor',
            'document_knowledge.group_document_user',
            'document_knowledge.group_ir_attachment_user',
        )

    @api.model
    def _get_view_group_hierarchy(self):
        hierarchy = deepcopy(super()._get_view_group_hierarchy())
        hidden_group_ids = {
            group.id
            for group in (
                self.env.ref(xmlid, raise_if_not_found=False)
                for xmlid in self._rms_hidden_user_form_group_xmlids()
            )
            if group
        }
        if not hidden_group_ids:
            return hierarchy

        hierarchy['groups'] = {
            group_id: group
            for group_id, group in hierarchy['groups'].items()
            if group_id not in hidden_group_ids
        }

        hidden_privilege_ids = set()
        for privilege_id, privilege in list(hierarchy['privileges'].items()):
            privilege['group_ids'] = [
                group_id
                for group_id in privilege['group_ids']
                if group_id not in hidden_group_ids
            ]
            if not privilege['group_ids']:
                hidden_privilege_ids.add(privilege_id)
                del hierarchy['privileges'][privilege_id]

        hierarchy['categories'] = [
            {
                **category,
                'privilege_ids': [
                    privilege_id
                    for privilege_id in category['privilege_ids']
                    if privilege_id not in hidden_privilege_ids
                ],
            }
            for category in hierarchy['categories']
        ]
        hierarchy['categories'] = [
            category
            for category in hierarchy['categories']
            if category['privilege_ids']
        ]
        return hierarchy
