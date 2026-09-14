from odoo import models, fields, api
from odoo.exceptions import ValidationError

ALLOWED_SERIAL_STATE_CODES = ('second_hand', 'ex_demo')


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    serial_ids = fields.One2many(
        'sale.order.line.serial', 'sale_order_line_id',
        string='Números de Serie',
        help="Números de serie concretos (2ª Mano / Ex-Demo) vendidos en esta línea."
    )
    serial_count = fields.Integer(compute='_compute_serial_count', string='Nº de series')

    @api.depends('serial_ids')
    def _compute_serial_count(self):
        for line in self:
            line.serial_count = len(line.serial_ids)

    @api.onchange('serial_ids')
    def _onchange_serial_ids_set_qty(self):
        for line in self:
            if line.serial_ids:
                line.product_uom_qty = len(line.serial_ids)

    @api.constrains('serial_ids', 'product_uom_qty')
    def _check_serial_ids_consistency(self):
        for line in self:
            if not line.serial_ids:
                continue
            states = line.serial_ids.lot_id.product_state_id
            if len(states) > 1:
                raise ValidationError(
                    f"Todos los números de serie de la línea '{line.product_id.display_name}' "
                    "deben estar en el mismo estado (no se pueden mezclar 2ª Mano y Ex-Demo en la misma línea)."
                )
            if line.product_uom_qty != len(line.serial_ids):
                raise ValidationError(
                    f"La cantidad de la línea '{line.product_id.display_name}' ({line.product_uom_qty}) "
                    f"debe coincidir con el número de series seleccionadas ({len(line.serial_ids)})."
                )

    @api.constrains('product_id')
    def _check_demo_state(self):
        for line in self:
            if line.product_id and line.product_id.product_tmpl_id.product_state_id.code == 'demo':
                raise ValidationError(
                    f"El producto '{line.product_id.name}' está en estado Demo y no puede ser presupuestado ni vendido."
                )

    @api.depends('product_id', 'product_uom_id', 'product_uom_qty', 'serial_ids', 'serial_ids.price_unit')
    def _compute_price_unit(self):
        super()._compute_price_unit()
        for line in self:
            if line.serial_ids:
                state_code = line.serial_ids[0].product_state_id.code
                if state_code in ALLOWED_SERIAL_STATE_CODES:
                    qty = len(line.serial_ids) or 1
                    unit_price = sum(line.serial_ids.mapped('price_unit')) / qty
                    line.price_unit = unit_price
                    line.technical_price_unit = unit_price
            # Si no hay series, comprobamos el estado general del producto
            elif line.product_id:
                product_state_code = line.product_id.product_tmpl_id.product_state_id.code
                if product_state_code in ('demo', 'discontinued'):
                    line.price_unit = 0.0
                    line.technical_price_unit = 0.0

    def _sync_second_hand_discount(self):
        """Aplica el 10% de descuento automático en líneas de 2ª Mano.

        El campo 'discount' de sale.order.line no tiene compute activo en
        este entorno (un módulo OCA de descuento triple -discount1/2/3- le
        quita el compute para volverlo editable a mano), así que no basta
        con un método @api.depends: el valor hay que escribirlo de forma
        explícita cuando cambian las series de la línea.
        """
        for line in self:
            if line.serial_ids and line.serial_ids[0].product_state_id.code == 'second_hand':
                if 'discount1' in line._fields:
                    line.discount1 = 10.0
                else:
                    line.discount = 10.0

    def action_open_serial_selector(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Vender como 2ª Mano / Ex-Demo',
            'res_model': 'sale.order.line.serial.selector.wizard',
            'view_mode': 'form',
            'views': [[False, 'form']],
            'target': 'new',
            'context': {'default_sale_order_line_id': self.id},
        }
