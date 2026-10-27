from odoo import fields, models
from odoo.exceptions import UserError


class InstallationProject(models.Model):
    _inherit = 'rms.installation.project'

    partner_portal_profile = fields.Selection(
        related='partner_id.portal_profile', string='Perfil de portal', readonly=True, groups='base.group_user',
    )

    def action_open_portal_invite_link(self):
        self.ensure_one()
        return self.partner_id.action_open_portal_invite_link()

    def _get_send_message_parts(self):
        parts = super()._get_send_message_parts()
        if self.portal_access_state == 'internal':
            raise UserError('El cliente es un usuario interno; elige un contacto de cliente.')
        if self.portal_access_state in ('none', 'invited'):
            values = self.env['rms.portal.invite.link']._prepare_for_partner(self.partner_id)
            if values['link_type'] == 'signup':
                parts['access_text'] = (
                    '\nEs tu primer acceso: crea tu contraseña aquí (válido durante '
                    '{hours} horas):\n{url}\n'
                ).format(hours=values['validity_hours'], url=values['url'])
        return parts
