from odoo import fields, models

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    rms_header_logo_right = fields.Binary(
        related='company_id.rms_header_logo_right',
        readonly=False,
        string="Header Logo (Right)"
    )
    rms_footer_logos = fields.Binary(
        related='company_id.rms_footer_logos',
        readonly=False,
        string="Footer Brands Ribbon"
    )
    rms_template_selection = fields.Selection(
        related='company_id.rms_template_selection',
        readonly=False,
        string="Selected Template"
    )
