from odoo import models, fields, api

class StockLot(models.Model):
    _inherit = 'stock.lot'

    product_state_id = fields.Many2one(
        'product.state',
        string='Estado',
        default=lambda self: self._default_product_state_id(),
        required=True,
        help="Estado físico/comercial de este número de serie"
    )
    custom_price = fields.Float(
        string='Precio Custom (Ex-Demo/2ª Mano)',
        digits='Product Price',
        help="Precio unitario específico para este número de serie"
    )
    product_state_code = fields.Char(
        related='product_state_id.code',
        string='Código de Estado',
        store=True
    )


    @api.model
    def _default_product_state_id(self):
        return self.env['product.state'].search([('code', '=', 'new')], limit=1)

    @api.onchange('product_id')
    def _onchange_product_id_set_state(self):
        if self.product_id and self.product_id.product_tmpl_id.product_state_id:
            self.product_state_id = self.product_id.product_tmpl_id.product_state_id
