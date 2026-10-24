from odoo import fields, models


class InstallationProjectSendMessage(models.TransientModel):
    _name = 'rms.installation.project.send.message'
    _description = 'Mensaje del proyecto para el cliente'

    message = fields.Text(string='Mensaje', readonly=True)
