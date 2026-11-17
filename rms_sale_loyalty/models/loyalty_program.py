from odoo import fields, models


class LoyaltyProgram(models.Model):
    _inherit = 'loyalty.program'

    rms_internal_note = fields.Text(string="Nota interna para comerciales")
