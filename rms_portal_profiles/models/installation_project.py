from odoo import fields, models


class InstallationProject(models.Model):
    _inherit = 'rms.installation.project'

    partner_portal_profile = fields.Selection(
        related='partner_id.portal_profile', string='Perfil de portal', readonly=True,
    )
