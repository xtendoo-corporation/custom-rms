# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    rms_sat_late_days = fields.Integer(string='Aviso del SAT: días en una fase',
                                       config_parameter='rms_repair_sat.late_days', default=7)
    rms_sat_used_price_factor = fields.Float(string='Precio de pieza de 2ª mano (fracción del precio nuevo)',
                                             config_parameter='rms_repair_sat.used_price_factor', default=0.5)
