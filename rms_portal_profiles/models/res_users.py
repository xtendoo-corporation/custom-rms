from odoo import api, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    @api.model_create_multi
    def create(self, vals_list):
        users = super().create(vals_list)
        users.filtered('share')._sync_portal_profile_from_partner()
        return users

    def write(self, vals):
        res = super().write(vals)
        if 'share' in vals or 'partner_id' in vals:
            self.filtered('share')._sync_portal_profile_from_partner()
        return res

    def _sync_portal_profile_from_partner(self):
        for user in self:
            user.partner_id._sync_portal_profile_groups()
