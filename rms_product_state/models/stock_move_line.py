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

    def write(self, vals):
        # Cambiar el nº de serie por programa (escáner, reserva) no pasa por el
        # onchange: sin esto la línea conservaría el estado del nº de serie
        # anterior y _action_done se lo copiaría al nuevo (un 2ª mano quedaría
        # como Nuevo). Un estado explícito en el mismo write manda.
        # Solo sigue al nº de serie nuevo si la línea tenía otro con su estado
        # heredado; en una recepción (sin nº de serie previo, o con estado
        # elegido a mano) se respeta el estado de la línea.
        if 'lot_id' in vals and 'product_state_id' not in vals:
            new_lot = self.env['stock.lot'].browse(vals['lot_id'])
            follow = self.filtered(
                lambda l: l.lot_id and l.lot_id != new_lot
                and l.product_state_id == l.lot_id.product_state_id)
            if follow:
                super(StockMoveLine, follow).write(dict(vals, product_state_id=new_lot.product_state_id.id))
                rest = self - follow
                return super(StockMoveLine, rest).write(vals) if rest else True
        return super().write(vals)

    def _action_done(self):
        res = super()._action_done()
        for line in self:
            if (line.product_state_id and line.lot_id
                    and line.lot_id.product_state_id != line.product_state_id):
                line.lot_id.product_state_id = line.product_state_id
        return res
