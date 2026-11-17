from odoo import api, models
from odoo.addons.rms_ventas_restriccion_comerciales.models.restrictions import (
    lock_prices_and_taxes,
)


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    def _is_free_product_reward_line(self):
        self.ensure_one()
        return self.reward_id.reward_type == 'product'

    def _filter_restricted_values(self, vals):
        vals = super()._filter_restricted_values(vals)
        if not self.env.su and lock_prices_and_taxes(self.env):
            # También se usa al limpiar los default_* del contexto en create.
            for field in ('reward_id', 'coupon_id', 'points_cost', 'reward_identifier_code'):
                vals.pop(field, None)
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        clean_vals = []
        for vals in vals_list:
            vals = self._filter_restricted_values(vals)
            reward_id = vals.get('reward_id', self.env.context.get('default_reward_id'))
            if (self.env.su or not lock_prices_and_taxes(self.env)) and reward_id:
                discount = 100 if self.env['loyalty.reward'].browse(reward_id).reward_type == 'product' else 0
                # Los componentes explícitos pueden impedir el precompute.
                vals.update(discount=discount, discount1=discount, discount2=0, discount3=0)
            clean_vals.append(vals)
        return super().create(clean_vals)

    def write(self, vals):
        vals = self._filter_restricted_values(vals)
        restricted = not self.env.su and lock_prices_and_taxes(self.env)
        result = True
        # Separar por recompensa permite escribir recordsets mixtos sin tocar
        # la cantidad de las líneas normales ni mezclar sus descuentos.
        for lines, discount in (
            (self.filtered(lambda line: line._is_free_product_reward_line()), 100),
            (self.filtered(lambda line: line.reward_id and not line._is_free_product_reward_line()), 0),
            (self.filtered(lambda line: not line.reward_id), None),
        ):
            if not lines:
                continue
            line_vals = dict(vals)
            if restricted and discount is not None:
                for field in (
                    'product_id', 'product_uom_qty', 'product_uom_id', 'product_uom',
                    'order_id', 'product_template_id', 'linked_line_id',
                ):
                    line_vals.pop(field, None)
            if 'reward_id' in line_vals:
                reward = self.env['loyalty.reward'].browse(line_vals['reward_id'])
                target_discount = (100 if reward.reward_type == 'product' else 0) if reward else None
            else:
                target_discount = discount
            if target_discount is not None:
                line_vals.update(discount=target_discount, discount1=target_discount, discount2=0, discount3=0)
            result = super(SaleOrderLine, lines).write(line_vals) and result
        return result

    @api.depends('product_id', 'product_uom_id', 'product_uom_qty', 'reward_id', 'reward_id.reward_type')
    def _compute_discount1(self):
        reward_lines = self.filtered('reward_id')
        for line in reward_lines:
            line.discount1 = 100 if line._is_free_product_reward_line() else 0
            line.discount2 = 0
            line.discount3 = 0
        other_lines = self - reward_lines
        if other_lines:
            super(SaleOrderLine, other_lines)._compute_discount1()

    def _compute_discounts(self):
        reward_lines = self.filtered('reward_id')
        other_lines = self - reward_lines
        if other_lines:
            super(SaleOrderLine, other_lines)._compute_discounts()
        reward_lines._compute_discount1()
        for line in reward_lines:
            line.discount = 100 if line._is_free_product_reward_line() else 0

    def _reset_loyalty(self, complete=False):
        if not self.env.su and lock_prices_and_taxes(self.env):
            self.order_id.check_access('write')
            # sudo: permitir al motor limpiar precio, puntos y recompensa.
            super(SaleOrderLine, self.sudo())._reset_loyalty(complete=complete)
            return self
        return super()._reset_loyalty(complete=complete)
