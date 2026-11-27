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

    rms_sat_no_discount = fields.Boolean(string='Servicio SAT sin descuento', copy=False)

    def _rms_apply_part_discounts(self):
        params = self.env['ir.config_parameter'].sudo()
        new_discount = float(params.get_param('rms_repair_sat.parts_discount', '30'))
        used_discount = float(params.get_param('rms_repair_sat.used_extra_discount', '50'))
        for line in self:
            custom = line.rms_used_alternative_of_id and line.rms_used_lot_id.custom_price
            values = {'discount1': 0 if custom else new_discount,
                      'discount2': used_discount if line.rms_used_alternative_of_id and not custom else 0,
                      'discount3': 0, 'discounting_type': 'multiplicative'}
            line.with_context(rms_sat_discount_update=True).write(values)

    def _rms_clear_service_discounts(self):
        self.with_context(rms_sat_discount_update=True).write({'rms_sat_no_discount': True,
            'discount1': 0, 'discount2': 0, 'discount3': 0, 'discounting_type': 'multiplicative'})

    def write(self, vals):
        result = super().write(vals)
        if not self.env.context.get('rms_sat_discount_update') and {'product_id', 'product_uom_qty', 'product_uom_id', 'serial_ids'}.intersection(vals):
            self.filtered('rms_sat_no_discount')._rms_clear_service_discounts()
            parts = self.filtered(lambda line: not line.rms_sat_no_discount and
                (line.rms_used_alternative_of_id or line.move_ids.filtered(
                    lambda move: move.repair_id and move.repair_line_type == 'add')))
            parts._rms_apply_part_discounts()
        return result

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        parts = lines.filtered(lambda line: not line.rms_sat_no_discount and
            (line.rms_used_alternative_of_id or line.move_ids.filtered(
                lambda move: move.repair_id and move.repair_line_type == 'add')))
        parts._rms_apply_part_discounts()
        return lines


class StockMove(models.Model):
    _inherit = 'stock.move'

    def write(self, vals):
        result = super().write(vals)
        if 'sale_line_id' in vals:
            lines = self.filtered(lambda move: move.repair_id and move.repair_line_type == 'add').sale_line_id
            lines.filtered(lambda line: not line.rms_sat_no_discount)._rms_apply_part_discounts()
        return result
