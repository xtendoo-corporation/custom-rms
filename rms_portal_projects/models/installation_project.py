import base64
import binascii

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


MAX_FILE_SIZE = 20 * 1024 * 1024


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
    user_id = fields.Many2one(
        'res.users', string='Responsable', default=lambda self: self.env.user, tracking=True,
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
    description = fields.Text(string='Notas internas')
    file_data = fields.Binary(string='Documento (HTML)', attachment=True)
    file_name = fields.Char(string='Nombre del archivo')
    company_id = fields.Many2one(
        'res.company', string='Compañía', default=lambda self: self.env.company,
    )

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
                raise ValidationError('El documento no puede superar los 20 MB.')

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

    def action_send(self):
        if any(not project.file_data for project in self):
            raise UserError('Añade un documento antes de enviar el proyecto al cliente.')
        for project in self:
            if project.state == 'draft':
                project.state = 'sent'

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
