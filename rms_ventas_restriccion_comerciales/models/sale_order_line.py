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

    def _filter_restricted_context(self):
        # Aplicar las mismas restricciones antes de que default_get lea el contexto.
        defaults = {key[8:]: value for key, value in self.env.context.items()
                    if key.startswith('default_')}
        allowed = self._filter_restricted_values(defaults)
        return {key: value for key, value in self.env.context.items()
                if not key.startswith('default_') or key[8:] in allowed}

    def _apply_pricelist_discounts(self):
        """Pone en las líneas los descuentos de la lista de precios del pedido.

        Los descuentos triples de la tarifa (product_pricelist_triple_discount)
        no se calculan solos al elegir producto: hay que pulsar «Actualizar
        precios», que los comerciales no pueden usar. Como tampoco pueden
        escribir descuentos a mano, sus líneas llevan siempre los de la tarifa.
        Las líneas con series (2ª mano / ex-demo) tienen su propio descuento.
        """
        if not hasattr(self, '_compute_discounts'):
            return
        lines = self.filtered(lambda line: line.product_id and not line.display_type and not (
            'serial_ids' in line._fields and line.serial_ids
        ))
        lines.with_context(force_pricelist_discounts=True)._compute_discounts()

    @api.onchange('product_id', 'product_uom_qty', 'product_uom_id')
    def _onchange_comercial_pricelist_discounts(self):
        if not self.env.su and lock_prices_and_taxes(self.env):
            self._apply_pricelist_discounts()

    @api.model_create_multi
    def create(self, vals_list):
        clean_self = self.with_context(self._filter_restricted_context())
        lines = super(SaleOrderLine, clean_self).create(
            [self._filter_restricted_values(vals) for vals in vals_list]
        )
        if not self.env.su and lock_prices_and_taxes(self.env):
            lines.sudo()._apply_pricelist_discounts()
        return lines

    def write(self, vals):
        res = super().write(self._filter_restricted_values(vals))
        if (not self.env.su and lock_prices_and_taxes(self.env)
                and {'product_id', 'product_uom_qty', 'product_uom_id'} & set(vals)):
            self.sudo()._apply_pricelist_discounts()
        return res
