from odoo import models, fields, api

class StockMove(models.Model):
    _inherit = 'stock.move'

    def _update_reserved_quantity(self, need, location_id, lot_id=None, package_id=None, owner_id=None, strict=True):
        # Si no se pasa un lote, pero el movimiento viene de una línea de venta con lote asignado, lo forzamos
        if not lot_id and self.sale_line_id and self.sale_line_id.lot_id:
            lot_id = self.sale_line_id.lot_id
        return super()._update_reserved_quantity(
            need, location_id, lot_id=lot_id, package_id=package_id, owner_id=owner_id, strict=strict
        )

    def _prepare_move_line_vals(self, quantity=None, reserved_quant=None):
        vals = super()._prepare_move_line_vals(quantity=quantity, reserved_quant=reserved_quant)
        # Si la línea de movimiento no tiene lote asignado, pero proviene de una venta con lote, lo asignamos
        if not vals.get('lot_id') and self.sale_line_id and self.sale_line_id.lot_id:
            vals['lot_id'] = self.sale_line_id.lot_id.id
        return vals
