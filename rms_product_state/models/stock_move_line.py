from odoo import models, fields, api


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    product_state_id = fields.Many2one(
        'product.state',
        string='Estado',
        default=lambda self: self.env['stock.lot']._default_product_state_id(),
        help="Estado (Nuevo, 2ª Mano, Demo, Ex-Demo...) con el que entra esta "
             "unidad/número de serie. Se copia al número de serie al validar."
    )

    def _action_done(self):
        res = super()._action_done()
        for line in self:
            if line.product_state_id and line.lot_id:
                line.lot_id.product_state_id = line.product_state_id
        return res
