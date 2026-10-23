# -*- coding: utf-8 -*-

from odoo import api, models, tools

from .restrictions import hide_pricelists

PRICELIST_MODELS = ('product.pricelist', 'product.pricelist.item')


class IrUiMenu(models.Model):
    _inherit = 'ir.ui.menu'

    @api.model
    def _visible_menu_ids(self, debug=False):
        visible_ids = super()._visible_menu_ids(debug)
        if hide_pricelists(self.env):
            visible_ids = visible_ids - self._get_pricelist_menu_ids()
        return visible_ids

    @api.model
    @tools.ormcache()
    def _get_pricelist_menu_ids(self):
        """Menús que abren listas de precios o sus reglas (Ventas, Web, TPV...)."""
        menus = self.sudo().with_context(active_test=False).search([('action', '!=', False)])
        return frozenset(
            menu.id for menu in menus
            if menu.action._name == 'ir.actions.act_window'
            and menu.action.exists()
            and menu.action.res_model in PRICELIST_MODELS
        )
