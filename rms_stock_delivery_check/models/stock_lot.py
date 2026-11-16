from odoo import _, models
from odoo.exceptions import AccessError


class StockLot(models.Model):
    _inherit = 'stock.lot'

    def write(self, vals):
        # Cambiar el estado de un equipo: solo el responsable de inventario.
        # (La validación de un movimiento copia el estado de la línea al nº de
        # serie —rms_product_state—: eso llega con el contexto de abajo.)
        if ('product_state_id' in vals and not self.env.su
                and not self.env.context.get('rms_state_from_move_done')
                and not self.env.user.has_group('stock.group_stock_manager')
                and any(lot.product_state_id.id != vals['product_state_id'] for lot in self)):
            raise AccessError(_(
                "Solo un responsable de inventario puede cambiar el estado de un equipo."))
        return super().write(vals)


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    def _action_done(self):
        # En una SALIDA el estado de la línea no puede cambiar el del equipo si
        # quien valida no es responsable: se deja el del nº de serie.
        if not self.env.su and not self.env.user.has_group('stock.group_stock_manager'):
            for line in self:
                if (line.lot_id and line.picking_code != 'incoming'
                        and line.product_state_id != line.lot_id.product_state_id):
                    line.product_state_id = line.lot_id.product_state_id
        return super(StockMoveLine, self.with_context(rms_state_from_move_done=True))._action_done()
