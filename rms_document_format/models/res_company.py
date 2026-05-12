from odoo import fields, models

class ResCompany(models.Model):
    _inherit = 'res.company'

    rms_header_logo_right = fields.Binary(string="Header Logo (Right)")
    rms_footer_logos = fields.Binary(string="Footer Brands Ribbon")
    rms_template_selection = fields.Selection([
        ('standard', 'Standard Odoo Template'),
        ('rms', 'RMS Custom Template'),
    ], string="Selected Template", default='standard')