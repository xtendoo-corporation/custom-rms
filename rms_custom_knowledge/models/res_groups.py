from odoo import api, models


class ResGroups(models.Model):
    _inherit = 'res.groups'

    @api.model
    def _get_view_group_hierarchy(self):
        hierarchy = super()._get_view_group_hierarchy()

        privilege = self.env.ref(
            'rms_custom_knowledge.res_groups_privilege_knowledge',
            raise_if_not_found=False,
        )
        category = self.env.ref(
            'document_knowledge.module_category_knowledge',
            raise_if_not_found=False,
        ) or self.env.ref(
            'rms_custom_knowledge.module_category_rms_knowledge',
            raise_if_not_found=False,
        )
        if not privilege or not category:
            return hierarchy

        if privilege.id in hierarchy['privileges']:
            hierarchy['privileges'][privilege.id]['category_id'] = category.id

        for category_data in hierarchy['categories']:
            category_data['privilege_ids'] = [
                privilege_id
                for privilege_id in category_data['privilege_ids']
                if privilege_id != privilege.id
            ]

        category_data = next(
            (
                existing_category
                for existing_category in hierarchy['categories']
                if existing_category['id'] == category.id
            ),
            None,
        )
        if category_data:
            category_data['name'] = 'Knowledge'
            category_data['privilege_ids'].append(privilege.id)
        else:
            hierarchy['categories'].append({
                'id': category.id,
                'name': 'Knowledge',
                'privilege_ids': [privilege.id],
            })

        return hierarchy
