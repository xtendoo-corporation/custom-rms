# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    rms_used_section = fields.Boolean(string='Sección de 2ª mano del SAT', copy=False)
    rms_used_alternative_of_id = fields.Many2one('sale.order.line', string='Alternativa de 2ª mano de',
                                                 copy=False, ondelete='cascade')
    rms_used_lot_id = fields.Many2one('stock.lot', string='Lote de 2ª mano propuesto', copy=False)

    @api.constrains('rms_used_lot_id', 'product_id')
    def _check_rms_used_lot(self):
        for line in self:
            if line.rms_used_lot_id and (line.product_id.tracking == 'none' or line.rms_used_lot_id.product_id != line.product_id):
                raise ValidationError('La pieza de 2ª mano debe tener un nº de serie o lote del producto.')
