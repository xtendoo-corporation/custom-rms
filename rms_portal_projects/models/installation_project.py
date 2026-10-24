import base64
import binascii

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


MAX_FILE_SIZE = 40 * 1024 * 1024


class InstallationProject(models.Model):
    _name = 'rms.installation.project'
    _description = 'Proyecto de Instalación (Portal Cliente)'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'

    name = fields.Char(string='Referencia', required=True, tracking=True)
    partner_id = fields.Many2one(
        'res.partner', string='Cliente', required=True, tracking=True,
        help='Único contacto que podrá ver este proyecto en su portal.',
    )
    portal_access_state = fields.Selection(
        [
            ('none', 'Sin acceso'),
            ('invited', 'Invitado, nunca ha entrado'),
            ('active', 'Activo'),
            ('internal', 'Usuario interno'),
        ],
        groups='base.group_user', string='Acceso al portal', compute='_compute_portal_access',
    )
    portal_last_login = fields.Datetime(
        groups='base.group_user', string='Último acceso al portal', compute='_compute_portal_access',
    )
    user_id = fields.Many2one(
        'res.users', groups='base.group_user', string='Responsable', default=lambda self: self.env.user, tracking=True,
    )
    date = fields.Date(string='Fecha', default=fields.Date.context_today, tracking=True)
    state = fields.Selection(
        [
            ('draft', 'Borrador'),
            ('sent', 'Enviado'),
            ('accepted', 'Aceptado'),
            ('rejected', 'Rechazado'),
        ],
        string='Estado', default='draft', required=True, tracking=True,
        help='Solo los proyectos en estado distinto de Borrador son visibles para el cliente en el portal.',
    )
    description = fields.Text(string='Notas internas', groups='base.group_user')
    file_data = fields.Binary(string='Documento (HTML)', attachment=True, groups='base.group_user')
    file_name = fields.Char(string='Nombre del archivo')
    company_id = fields.Many2one(
        'res.company', groups='base.group_user', string='Compañía', default=lambda self: self.env.company,
    )

    @api.depends('partner_id')
    def _compute_portal_access(self):
        for project in self:
            users = project.partner_id.sudo().with_context(active_test=False).user_ids
            portal_user = users.filtered(
                lambda user: user.share and user.active and user._is_portal()
            )[:1]
            last_login = portal_user.login_date if portal_user else False
            if any(user._is_internal() for user in users):
                state = 'internal'
            elif not portal_user:
                state = 'none'
            else:
                state = 'active' if last_login else 'invited'
            project.portal_access_state = state
            project.portal_last_login = last_login

    @api.constrains('file_data', 'file_name')
    def _check_document(self):
        for project in self:
            if not project.file_data:
                continue
            if not (project.file_name or '').lower().endswith(('.html', '.htm')):
                raise ValidationError('El documento debe tener extensión .html o .htm.')
            try:
                size = len(base64.b64decode(project.file_data))
            except (ValueError, binascii.Error):
                raise ValidationError('El documento no contiene datos válidos en base64.') from None
            if size > MAX_FILE_SIZE:
                raise ValidationError('El documento no puede superar los 40 MB.')

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and not self.env.user.has_group('base.group_erp_manager'):
            for vals in vals_list:
                vals['user_id'] = self.env.uid
        return super().create(vals_list)

    def write(self, vals):
        if (
            'user_id' in vals
            and not self.env.su
            and not self.env.user.has_group('base.group_erp_manager')
            and any(vals['user_id'] != project.user_id.id for project in self)
        ):
            raise AccessError('Solo un administrador puede cambiar el responsable del proyecto.')
        protected_fields = {'partner_id', 'file_data', 'file_name'} & vals.keys()
        for project in self:
            if project.state != 'draft' and any(
                vals[name] != (project.partner_id.id if name == 'partner_id' else project[name])
                for name in protected_fields
            ):
                raise UserError(
                    'Vuelve el proyecto a borrador antes de cambiar el cliente o el documento.'
                )
        return super().write(vals)

    def _get_send_message_parts(self):
        self.ensure_one()
        return {
            'greeting_name': self.partner_id.name,
            'project_name': self.name,
            'project_url': self.get_base_url() + '/my/installation-projects/%s' % self.id,
            'access_text': '',
            'signature': self.env.user.name,
        }

    def _build_send_message(self):
        self.ensure_one()
        return (
            'Hola {greeting_name},\n\n'
            'Ya tienes disponible el proyecto «{project_name}» en nuestro portal:\n'
            '{project_url}\n{access_text}\nUn saludo,\n{signature}'
        ).format(**self._get_send_message_parts())

    def _open_send_message(self, message):
        self.ensure_one()
        wizard = self.env['rms.installation.project.send.message'].create({'message': message})
        return {
            'type': 'ir.actions.act_window',
            'name': 'Mensaje para el cliente',
            'res_model': wizard._name,
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_send(self):
        self.ensure_one()
        if not self.file_data:
            raise UserError('Añade un documento antes de enviar el proyecto al cliente.')
        if self.state != 'draft':
            raise UserError('Solo se puede enviar un proyecto en borrador.')
        message = self._build_send_message()
        self.state = 'sent'
        self.message_post(
            body='Enviado al cliente por %s' % self.env.user.name,
            message_type='comment',
            subtype_xmlid='mail.mt_note',
        )
        return self._open_send_message(message)

    def action_open_send_message(self):
        self.ensure_one()
        return self._open_send_message(self._build_send_message())

    def action_mark_accepted(self):
        if any(project.state != 'sent' for project in self):
            raise UserError('Solo se puede marcar como aceptado un proyecto enviado.')
        self.write({'state': 'accepted'})

    def action_mark_rejected(self):
        if any(project.state != 'sent' for project in self):
            raise UserError('Solo se puede marcar como rechazado un proyecto enviado.')
        self.write({'state': 'rejected'})

    def action_reset_to_draft(self):
        self.write({'state': 'draft'})
