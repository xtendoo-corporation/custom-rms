# -*- coding: utf-8 -*-

from odoo import api, models

from .restrictions import lock_prices_and_taxes


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    def _filter_restricted_values(self, vals):
        vals = dict(vals)
        if not self.env.su and lock_prices_and_taxes(self.env):
            for field in ('price_unit', 'discount', 'discount1', 'discount2', 'discount3', 'tax_ids'):
                if field in self._fields:
                    vals.pop(field, None)
        # Sin compute, create usa el valor por defecto y write conserva el
        # anterior. Los precios de series se sincronizan internamente.
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        return super().create([self._filter_restricted_values(vals) for vals in vals_list])

    def write(self, vals):
        return super().write(self._filter_restricted_values(vals))
