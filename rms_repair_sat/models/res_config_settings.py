# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    rms_sat_late_days = fields.Integer(string='Aviso del SAT: días en una fase',
                                       config_parameter='rms_repair_sat.late_days', default=7)
    rms_sat_parts_discount = fields.Float(string='Descuento de piezas nuevas (%)',
        config_parameter='rms_repair_sat.parts_discount', default=30)
    rms_sat_used_extra_discount = fields.Float(string='Descuento adicional de piezas de 2ª mano (%)',
        config_parameter='rms_repair_sat.used_extra_discount', default=50)

    rms_sat_default_warranty_months = fields.Integer(string='Garantía por defecto (meses)', config_parameter='rms_repair_sat.default_warranty_months', default=24)
    rms_sat_receipt_terms = fields.Html(string='Condiciones del resguardo')

    def get_values(self):
        values = super().get_values()
        values['rms_sat_receipt_terms'] = self.env['ir.config_parameter'].sudo().get_param('rms_repair_sat.receipt_terms', '')
        return values

    def set_values(self):
        super().set_values()
        self.env['ir.config_parameter'].sudo().set_param('rms_repair_sat.receipt_terms', self.rms_sat_receipt_terms or '')
