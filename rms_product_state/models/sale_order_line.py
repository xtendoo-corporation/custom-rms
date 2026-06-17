from odoo import models, fields, api
from odoo.exceptions import ValidationError

class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    lot_id = fields.Many2one(
        'stock.lot',
        string='Nº Serie/Lote',
        domain="[('product_id', '=', product_id)]",
        help="Seleccione el número de serie específico para productos Ex-Demo o 2ª Mano"
    )

    @api.constrains('product_id', 'lot_id')
    def _check_demo_state(self):
        for line in self:
            if line.product_id and line.product_id.product_tmpl_id.product_state_id.code == 'demo':
                raise ValidationError(
                    f"El producto '{line.product_id.name}' está en estado Demo y no puede ser presupuestado ni vendido."
                )
            if line.lot_id and line.lot_id.product_state_id.code == 'demo':
                raise ValidationError(
                    f"El número de serie '{line.lot_id.name}' está en estado Demo y no puede ser presupuestado ni vendido."
                )

    @api.depends('product_id', 'product_uom_id', 'product_uom_qty', 'lot_id')
    def _compute_price_unit(self):
        super()._compute_price_unit()
        for line in self:
            # Si hay lote asignado
            if line.lot_id:
                state_code = line.lot_id.product_state_id.code
                if state_code in ('ex_demo', 'second_hand'):
                    line.price_unit = line.lot_id.custom_price
                    line.technical_price_unit = line.lot_id.custom_price
                elif state_code in ('demo', 'discontinued'):
                    line.price_unit = 0.0
                    line.technical_price_unit = 0.0
            # Si no hay lote, comprobamos el estado general del producto
            elif line.product_id:
                product_state_code = line.product_id.product_tmpl_id.product_state_id.code
                if product_state_code in ('demo', 'discontinued'):
                    line.price_unit = 0.0
                    line.technical_price_unit = 0.0

    @api.depends('product_id', 'product_uom_id', 'product_uom_qty', 'lot_id')
    def _compute_discount(self):
        super()._compute_discount()
        for line in self:
            if line.lot_id and line.lot_id.product_state_id.code == 'second_hand':
                line.discount = 10.0
