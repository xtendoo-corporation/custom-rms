# -*- coding: utf-8 -*-
from odoo import fields, models


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    rms_used_section = fields.Boolean(string='Sección de 2ª mano del SAT', copy=False)
    rms_used_alternative_of_id = fields.Many2one('sale.order.line', string='Alternativa de 2ª mano de',
                                                 copy=False, ondelete='cascade')
    rms_used_lot_id = fields.Many2one('stock.lot', string='Lote de 2ª mano propuesto', copy=False)
