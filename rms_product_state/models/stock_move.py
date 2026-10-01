from odoo import models, fields, api

class StockMove(models.Model):
    _inherit = 'stock.move'

    def _get_pending_sale_serial_lot(self):
        """Próximo lote de sale.order.line.serial de este movimiento aún no reservado."""
        self.ensure_one()
        if not self.sale_line_id or not self.sale_line_id.serial_ids:
            return self.env['stock.lot']
        chosen_lots = self.sale_line_id.serial_ids.lot_id
        already_reserved = self.move_line_ids.filtered(
            lambda l: l.lot_id in chosen_lots
        ).lot_id
        remaining = chosen_lots - already_reserved
        return remaining[:1]

    def _update_reserved_quantity(self, need, location_id, lot_id=None, package_id=None, owner_id=None, strict=True):
        if not lot_id and self.sale_line_id:
            pending_lot = self._get_pending_sale_serial_lot()
            if pending_lot:
                lot_id = pending_lot
        return super()._update_reserved_quantity(
            need, location_id, lot_id=lot_id, package_id=package_id, owner_id=owner_id, strict=strict
        )

    def _prepare_move_line_vals(self, quantity=None, reserved_quant=None):
        vals = super()._prepare_move_line_vals(quantity=quantity, reserved_quant=reserved_quant)
        if not vals.get('lot_id') and self.sale_line_id:
            pending_lot = self._get_pending_sale_serial_lot()
            if pending_lot:
                vals['lot_id'] = pending_lot.id
        return vals
