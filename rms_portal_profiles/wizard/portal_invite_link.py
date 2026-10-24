from urllib.parse import urlencode as url_encode, urljoin

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
        if not (
            self.env.user.has_group('base.group_erp_manager')
            or self.env.user.has_group('rms_portal_projects.group_installation_project_manager')
        ):
            raise AccessError(_('Solo los administradores y los gestores de proyectos pueden generar enlaces de invitación al portal.'))

    @api.model
    def _prepare_for_partner(self, partner):
        """Concede el acceso al portal si hace falta y devuelve los valores del
        asistente con el enlace ya generado."""
        self._check_manager()
        partner.ensure_one()
        partner.check_access('read')
        is_admin = self.env.user.has_group('base.group_erp_manager')
        partner = partner.sudo()
        if not partner.email:
            raise UserError(_('El contacto "%s" no tiene correo electrónico.', partner.display_name))

        users = partner.with_context(active_test=False).user_ids
        if any(u._is_internal() for u in users):
            raise UserError(_('El contacto "%s" es un usuario interno, no de portal.', partner.display_name))

        portal_users = users.filtered(lambda u: u._is_portal())
        # Odoo 19: login_date is related to log_ids.create_date. Include
        # archived accounts so reactivation cannot bypass this restriction.
        if not is_admin and any(user.login_date or user.log_ids for user in users):
            raise UserError(_('Este contacto ya usa el portal; para restablecer su contraseña pídeselo a un administrador.'))

        portal_user = portal_users.filtered('active')[:1]
        if not portal_user:
            if not is_admin and not users:
                partner.write({'portal_profile': 'customer'})
            # Concede el acceso con el asistente estándar: crea/reactiva el
            # usuario portal y prepara el registro. El correo de invitación que
            # envía queda bloqueado por rms_mail_server.
            wizard = self.env['portal.wizard'].sudo().create({'partner_ids': [(6, 0, partner.ids)]})
            wizard.user_ids.filtered(lambda w: w.partner_id == partner).action_grant_access()
            portal_user = partner.with_context(active_test=False).user_ids.filtered(
                lambda user: user.active and user.share and user._is_portal()
            )[:1]

        if not portal_user or not portal_user.share or not portal_user._is_portal():
            raise UserError(_('No se ha podido conceder acceso de portal a este contacto.'))

        # Si ya ha entrado alguna vez, un enlace de registro no le sirve:
        # generamos uno de restablecer contraseña.
        link_type = 'reset' if portal_user.login_date else 'signup'
        partner.signup_prepare(signup_type=link_type)
        # Con varias BD en el dbfilter, /web/signup sin sesión da 404: se entra
        # por /web/login (que sí aplica ?db=) y de ahí se salta al registro.
        # Ver controllers/signup_redirect.py.
        relative = partner.with_context(relative_url=True)._get_signup_url_for_action()[partner.id]
        url = urljoin(partner.get_base_url(), '/web/login?' + url_encode({
            'db': self.env.cr.dbname,
            'redirect': relative,
        }))

        if link_type == 'reset':
            param, default = 'auth_signup.reset_password.validity.hours', 4
        else:
            param, default = 'auth_signup.signup.validity.hours', 144
        validity = int(self.env['ir.config_parameter'].sudo().get_param(param, default))

        partner.message_post(
            body=_('%(user)s generó un enlace de portal de tipo: %(link_type)s.',
                   user=self.env.user.display_name,
                   link_type=_('registro') if link_type == 'signup' else _('restablecer contraseña')),
            author_id=self.env.user.partner_id.id,
            subtype_xmlid='mail.mt_note',
        )

        return {
            'partner_id': partner.id,
            'link_type': link_type,
            'url': url,
            'validity_hours': validity,
            'login': portal_user.login,
        }
