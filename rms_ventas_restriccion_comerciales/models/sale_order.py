# -*- coding: utf-8 -*-

from odoo import api, models

from .restrictions import hide_pricelists, lock_prices_and_taxes


class SaleOrder(models.Model):
    _inherit = 'sale.order'

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
