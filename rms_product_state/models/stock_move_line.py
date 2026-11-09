from odoo import models, fields, api


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    product_state_id = fields.Many2one(
        'product.state',
        string='Estado',
        help="Estado (Nuevo, 2ª Mano, Demo, Ex-Demo...) con el que entra esta "
             "unidad/número de serie. Se copia al número de serie al validar."
    )

    @api.onchange('lot_id')
    def _onchange_lot_id_product_state(self):
        for line in self:
            line.product_state_id = line.lot_id.product_state_id

    @api.model_create_multi
    def create(self, vals_list):
        # Inventory adjustments and internal moves do not run UI onchanges.
        # Only initialise missing values: an explicit reception state wins.
        vals_list = [dict(vals) for vals in vals_list]
        for vals in vals_list:
            if 'product_state_id' not in vals and vals.get('lot_id'):
                vals['product_state_id'] = self.env['stock.lot'].browse(
                    vals['lot_id']
                ).product_state_id.id
        return super().create(vals_list)

    def _action_done(self):
        res = super()._action_done()
        for line in self:
            if (line.product_state_id and line.lot_id
                    and line.lot_id.product_state_id != line.product_state_id):
                line.lot_id.product_state_id = line.product_state_id
        return res
