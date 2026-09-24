from odoo import fields, models
from odoo.http import request


class ResUsers(models.Model):
    _inherit = 'res.users'

    def _update_last_login(self):
        res = super()._update_last_login()
        if self.share:
            ip_address = request.httprequest.environ.get('REMOTE_ADDR') if request else False
            self.env['rms.portal.access.log'].sudo().create({
                'partner_id': self.partner_id.id,
                'user_id': self.id,
                'login': self.login,
                'login_date': fields.Datetime.now(),
                'ip_address': ip_address,
                'portal_profile': self.partner_id.portal_profile,
            })
        return res
