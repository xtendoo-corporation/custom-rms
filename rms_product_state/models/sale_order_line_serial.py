from odoo import models, fields, api
from odoo.exceptions import ValidationError

ALLOWED_SERIAL_STATE_CODES = ('second_hand', 'ex_demo')


class SaleOrderLineSerial(models.Model):
    _name = 'sale.order.line.serial'
    _description = 'Número de serie (2ª Mano / Ex-Demo) de una línea de venta'
    _rec_name = 'lot_id'

    sale_order_line_id = fields.Many2one(
        'sale.order.line', string='Línea de venta', required=True, ondelete='cascade'
    )
    product_id = fields.Many2one(related='sale_order_line_id.product_id', store=True)
    lot_id = fields.Many2one(
        'stock.lot', string='Nº Serie/Lote', required=True,
        domain="[('product_id', '=', product_id)]"
    )
    product_state_id = fields.Many2one(
        related='lot_id.product_state_id', string='Estado', store=True
    )
    price_unit = fields.Float(
        string='Precio unitario', digits='Product Price',
        help='Precio de venta de esta unidad concreta (por defecto, el Precio Custom del lote al añadirlo).'
    )

    _lot_unique_per_line = models.Constraint(
        'UNIQUE(lot_id, sale_order_line_id)',
        'Este número de serie ya está añadido en esta línea.',
    )

    def _lock_prices(self):
        # Este módulo también funciona sin instalar las restricciones comerciales.
        commercial = self.env.ref('custom.comerciales', raise_if_not_found=False)
        allowed = self.env.ref(
            'rms_ventas_restriccion_comerciales.group_comerciales_quotation_full_edit',
            raise_if_not_found=False,
        )
        return not self.env.su and bool(commercial) and self.env.user.has_group(
            'custom.comerciales'
        ) and not (allowed and self.env.user.has_group(
            'rms_ventas_restriccion_comerciales.group_comerciales_quotation_full_edit'
        ))

    @api.constrains('lot_id', 'sale_order_line_id', 'product_id')
    def _check_lot_product(self):
        for rec in self:
            if rec.lot_id.product_id != rec.sale_order_line_id.product_id:
                raise ValidationError('El lote debe pertenecer al producto de la línea de venta.')

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [dict(vals) for vals in vals_list]
        for vals in vals_list:
            if self._lock_prices():
                vals.pop('price_unit', None)
            if vals.get('lot_id') and 'price_unit' not in vals:
                vals['price_unit'] = self.env['stock.lot'].browse(vals['lot_id']).custom_price
        records = super().create(vals_list)
        records._check_state_allowed()
        records._check_lot_not_sold_elsewhere()
        records.sale_order_line_id._sync_serial_state_discount()
        return records

    def write(self, vals):
        vals = dict(vals)
        if self._lock_prices():
            # Cada registro puede tener un lote y un precio custom diferentes.
            for rec in self:
                lot = self.env['stock.lot'].browse(vals.get('lot_id', rec.lot_id.id))
                super(SaleOrderLineSerial, rec).write(dict(vals, price_unit=lot.custom_price))
            res = True
        else:
            res = super().write(vals)
        if 'lot_id' in vals:
            self._check_state_allowed()
            self._check_lot_not_sold_elsewhere()
        self.sale_order_line_id._sync_serial_state_discount()
        return res

    def unlink(self):
        lines = self.sale_order_line_id
        res = super().unlink()
        # Si ya no quedan series, la línea vuelve a "Nuevo": hay que
        # recalcular el descuento (y no dejar el 10%/0% pegado).
        lines.filtered(lambda l: not l.serial_ids)._sync_serial_state_discount()
        return res

    def _check_state_allowed(self):
        for rec in self:
            if rec.lot_id.product_state_id.code not in ALLOWED_SERIAL_STATE_CODES:
                raise ValidationError(
                    f"El número de serie '{rec.lot_id.name}' está en estado "
                    f"'{rec.lot_id.product_state_id.name}'. Solo se pueden vender por número de serie "
                    "unidades en estado 2ª Mano o Ex-Demo."
                )

    def _check_lot_not_sold_elsewhere(self):
        for rec in self:
            # sudo: la unicidad es global; las reglas por vendedor ocultarían
            # las asignaciones de otros comerciales.
            other = self.sudo().search([
                ('lot_id', '=', rec.lot_id.id),
                ('id', '!=', rec.id),
                ('sale_order_line_id.order_id.state', '!=', 'cancel'),
            ])
            if other:
                orders = other.sale_order_line_id.order_id.mapped('name')
                raise ValidationError(
                    f"El número de serie '{rec.lot_id.name}' ya está asignado en otro presupuesto/pedido "
                    f"activo ({', '.join(orders)})."
                )
