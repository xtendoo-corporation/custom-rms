# -*- coding: utf-8 -*-

from odoo import api, models
from odoo.exceptions import AccessError

from .restrictions import hide_pricelists, lock_prices_and_taxes


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _filter_restricted_values(self, vals):
        vals = dict(vals)
        if not self.env.su:
            locked = lock_prices_and_taxes(self.env)
            if locked:
                vals.pop('fiscal_position_id', None)
            if locked or hide_pricelists(self.env):
                vals.pop('pricelist_id', None)
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        # Limpiar también los defaults que heredarían las líneas anidadas.
        context = self.env['sale.order.line']._filter_restricted_context()
        defaults = {key[8:]: value for key, value in context.items()
                    if key.startswith('default_')}
        allowed = self._filter_restricted_values(defaults)
        context = {key: value for key, value in context.items()
                   if not key.startswith('default_') or key[8:] in allowed}
        clean_self = self.with_context(context)
        return super(SaleOrder, clean_self).create(
            [self._filter_restricted_values(vals) for vals in vals_list]
        )

    def write(self, vals):
        return super().write(self._filter_restricted_values(vals))

    def _check_price_update_access(self, pricelist=False):
        if not self.env.su and (
            lock_prices_and_taxes(self.env) or (pricelist and hide_pricelists(self.env))
        ):
            raise AccessError('No tienes permiso para modificar precios, descuentos o impuestos.')

    def action_update_taxes(self):
        self._check_price_update_access()
        return super().action_update_taxes()

    def action_update_prices(self):
        self._check_price_update_access(pricelist=True)
        return super().action_update_prices()

    def action_open_discount_wizard(self):
        self._check_price_update_access()
        return super().action_open_discount_wizard()

    @api.model
    def _get_view_cache_key(self, view_id=None, view_type='form', **options):
        # La vista procesada se cachea una sola vez para todos los usuarios, así
        # que la clave debe distinguir qué restricciones se aplican.
        key = super()._get_view_cache_key(view_id, view_type, **options)
        return key + (hide_pricelists(self.env), lock_prices_and_taxes(self.env))

    @api.model
    def _get_view(self, view_id=None, view_type='form', **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        if hide_pricelists(self.env):
            # El campo se mantiene (invisible) para que la lista de precios se
            # siga calculando a partir del cliente y se guarde con el pedido.
            for node in arch.xpath(
                "//field[@name='pricelist_id']"
                " | //label[@for='pricelist_id']"
                " | //div[field[@name='pricelist_id']]"
                " | //button[@name='action_update_prices']"
            ):
                node.set('invisible', '1')
        if lock_prices_and_taxes(self.env):
            # force_save: el valor que calcula Odoo al elegir producto o cliente
            # tiene que guardarse aunque el usuario no pueda editarlo.
            # discount1/2/3 son los del descuento triple (sale_triple_discount).
            for node in arch.xpath(
                "//field[@name='order_line']//field[@name='price_unit' or @name='tax_ids'"
                " or @name='discount' or @name='discount1' or @name='discount2' or @name='discount3']"
                " | //field[@name='fiscal_position_id']"
            ):
                node.set('readonly', '1')
                node.set('force_save', '1')
            # Recalcular impuestos tras cambiar la posición fiscal es otra forma
            # de cambiar el IVA de las líneas, y el asistente de descuento
            # aplica un descuento a todo el presupuesto.
            for node in arch.xpath(
                "//button[@name='action_update_taxes' or @name='action_open_discount_wizard']"
            ):
                node.set('invisible', '1')
        return arch, view
