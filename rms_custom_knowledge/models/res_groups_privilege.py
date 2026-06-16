from odoo import api, models


class ResGroupsPrivilege(models.Model):
    _inherit = 'res.groups.privilege'

    @api.model_create_multi
    def create(self, vals_list):
        privileges = super().create(vals_list)
        self.env.registry.clear_cache('groups')
        return privileges

    def write(self, vals):
        result = super().write(vals)
        if {'name', 'sequence', 'category_id', 'placeholder'} & set(vals):
            self.env.registry.clear_cache('groups')
        return result

    def unlink(self):
        result = super().unlink()
        self.env.registry.clear_cache('groups')
        return result
