from odoo import fields, models


class PortalAccessLog(models.Model):
    _name = 'rms.portal.access.log'
    _description = 'Acceso al Portal de Clientes'
    _order = 'login_date desc'
    _rec_name = 'login'

    partner_id = fields.Many2one('res.partner', string='Contacto', index=True, readonly=True)
    user_id = fields.Many2one('res.users', string='Usuario', index=True, readonly=True)
    login = fields.Char(string='Login', readonly=True)
    login_date = fields.Datetime(string='Fecha de acceso', required=True, index=True, readonly=True)
    ip_address = fields.Char(string='Dirección IP', readonly=True)
    portal_profile = fields.Selection(
        [
            ('customer', 'Cliente'),
            ('marketing', 'Colaborador de Marketing'),
            ('projects', 'Proyectos'),
        ],
        string='Perfil de portal', readonly=True,
    )
