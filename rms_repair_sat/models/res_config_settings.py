# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    rms_sat_late_days = fields.Integer(string='Aviso del SAT: días en una fase',
                                       config_parameter='rms_repair_sat.late_days', default=7)
    rms_sat_used_price_factor = fields.Float(string='Precio de pieza de 2ª mano (fracción del precio nuevo)',
                                             config_parameter='rms_repair_sat.used_price_factor', default=0.5)

    rms_sat_default_warranty_months = fields.Integer(string='Garantía por defecto (meses)', config_parameter='rms_repair_sat.default_warranty_months', default=24)
    rms_sat_receipt_terms = fields.Html(string='Condiciones del resguardo')

    def get_values(self):
        values = super().get_values()
        values['rms_sat_receipt_terms'] = self.env['ir.config_parameter'].sudo().get_param('rms_repair_sat.receipt_terms', '')
        return values

    def set_values(self):
        super().set_values()
        self.env['ir.config_parameter'].sudo().set_param('rms_repair_sat.receipt_terms', self.rms_sat_receipt_terms or '')
