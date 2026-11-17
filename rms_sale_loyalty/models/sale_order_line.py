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
                if self.env['loyalty.reward'].browse(reward_id).reward_type == 'product':
                    # Los componentes explícitos pueden impedir el precompute.
                    vals.update(discount=100, discount1=100, discount2=0, discount3=0)
            clean_vals.append(vals)
        return super().create(clean_vals)

    def write(self, vals):
        vals = self._filter_restricted_values(vals)
        if 'reward_id' in vals:
            reward = self.env['loyalty.reward'].browse(vals['reward_id'])
            free_lines = self if reward.reward_type == 'product' else self.browse()
        else:
            free_lines = self.filtered(lambda line: line._is_free_product_reward_line())
        other_lines = self - free_lines
        result = True
        if other_lines:
            result = super(SaleOrderLine, other_lines).write(dict(vals))
        if free_lines:
            # Mantener la invariante también si llegan componentes explícitos.
            free_vals = dict(vals, discount=100, discount1=100, discount2=0, discount3=0)
            result = super(SaleOrderLine, free_lines).write(free_vals) and result
        return result

    @api.depends('product_id', 'product_uom_id', 'product_uom_qty', 'reward_id', 'reward_id.reward_type')
    def _compute_discount1(self):
        free_lines = self.filtered(lambda line: line._is_free_product_reward_line())
        for line in free_lines:
            line.discount1 = 100
            line.discount2 = 0
            line.discount3 = 0
        other_lines = self - free_lines
        if other_lines:
            super(SaleOrderLine, other_lines)._compute_discount1()

    def _compute_discounts(self):
        free_lines = self.filtered(lambda line: line._is_free_product_reward_line())
        other_lines = self - free_lines
        if other_lines:
            super(SaleOrderLine, other_lines)._compute_discounts()
        free_lines._compute_discount1()
        for line in free_lines:
            line.discount = 100

    def _reset_loyalty(self, complete=False):
        if not self.env.su and lock_prices_and_taxes(self.env):
            # sudo: permitir al motor limpiar precio, puntos y recompensa.
            super(SaleOrderLine, self.sudo())._reset_loyalty(complete=complete)
            return self
        return super()._reset_loyalty(complete=complete)
