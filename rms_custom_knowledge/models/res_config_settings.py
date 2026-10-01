from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    onlyoffice_server_url = fields.Char(
        string='URL del servidor OnlyOffice',
        config_parameter='rms_custom_knowledge.onlyoffice_server_url',
        help='URL pública del OnlyOffice Document Server, p.ej. https://office.tudominio.com',
    )
    onlyoffice_jwt_secret = fields.Char(
        string='Secreto JWT de OnlyOffice',
        config_parameter='rms_custom_knowledge.onlyoffice_jwt_secret',
        help='Debe coincidir con la variable JWT_SECRET del Document Server. Déjalo vacío si el servidor no usa JWT.',
    )
