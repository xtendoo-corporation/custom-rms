# -*- coding: utf-8 -*-

from odoo import models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def action_add_from_catalog(self):
        result = super().action_add_from_catalog()
        if result.get('res_model') == 'product.product':
            list_view = self.env.ref(
                'rms_sale_catalog_no_variant_color.product_view_list_catalog'
            )
            views = list(result['views'])
            views.insert(1, (list_view.id, 'list'))
            result['views'] = views
        return result
