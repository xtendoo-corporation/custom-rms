from odoo import fields, models


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

    def action_send(self):
        for project in self:
            if project.state == 'draft':
                project.state = 'sent'

    def action_reset_to_draft(self):
        self.write({'state': 'draft'})
