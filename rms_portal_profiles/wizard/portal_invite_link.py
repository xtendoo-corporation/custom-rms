from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError


class RmsPortalInviteLink(models.TransientModel):
    """Genera el enlace de registro / acceso al portal para copiarlo y enviarlo
    a mano, ya que rms_mail_server bloquea los correos a dominios externos."""
    _name = 'rms.portal.invite.link'
    _description = 'Enlace de invitación al portal'

    partner_id = fields.Many2one('res.partner', string='Contacto', required=True, readonly=True)
    link_type = fields.Selection(
        [('signup', 'Registro (primer acceso)'), ('reset', 'Restablecer contraseña')],
        string='Tipo de enlace', readonly=True,
    )
    url = fields.Char(string='Enlace', readonly=True)
    validity_hours = fields.Integer(string='Válido durante (horas)', readonly=True)
    login = fields.Char(string='Usuario (login)', readonly=True)

    @api.model
    def _check_manager(self):
        if not self.env.user.has_group('base.group_erp_manager'):
            raise AccessError(_('Solo los administradores pueden generar enlaces de invitación al portal.'))

    @api.model
    def _prepare_for_partner(self, partner):
        """Concede el acceso al portal si hace falta y devuelve los valores del
        asistente con el enlace ya generado."""
        self._check_manager()
        partner = partner.sudo()
        if not partner.email:
            raise UserError(_('El contacto "%s" no tiene correo electrónico.', partner.display_name))

        users = partner.with_context(active_test=False).user_ids
        if any(u._is_internal() for u in users):
            raise UserError(_('El contacto "%s" es un usuario interno, no de portal.', partner.display_name))

        portal_user = users.filtered(lambda u: u.active and u._is_portal())[:1]
        if not portal_user:
            # Concede el acceso con el asistente estándar: crea/reactiva el
            # usuario portal y prepara el registro. El correo de invitación que
            # envía queda bloqueado por rms_mail_server.
            wizard = self.env['portal.wizard'].sudo().create({'partner_ids': [(6, 0, partner.ids)]})
            wizard.user_ids.filtered(lambda w: w.partner_id == partner).action_grant_access()
            portal_user = partner.with_context(active_test=False).user_ids.filtered('active')[:1]

        # Si ya ha entrado alguna vez, un enlace de registro no le sirve:
        # generamos uno de restablecer contraseña.
        link_type = 'reset' if portal_user.login_date else 'signup'
        partner.signup_prepare(signup_type=link_type)
        url = partner._get_signup_url_for_action()[partner.id]

        if link_type == 'reset':
            param, default = 'auth_signup.reset_password.validity.hours', 4
        else:
            param, default = 'auth_signup.signup.validity.hours', 144
        validity = int(self.env['ir.config_parameter'].sudo().get_param(param, default))

        return {
            'partner_id': partner.id,
            'link_type': link_type,
            'url': url,
            'validity_hours': validity,
            'login': portal_user.login,
        }
