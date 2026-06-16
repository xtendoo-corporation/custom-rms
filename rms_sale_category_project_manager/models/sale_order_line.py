# -*- coding: utf-8 -*-

from odoo import api, models


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines.mapped('order_id')._subscribe_category_project_managers()
        return lines

    def write(self, vals):
        orders = self.mapped('order_id')
        result = super().write(vals)
        if {'product_id', 'order_id'} & set(vals):
            (orders | self.mapped('order_id'))._subscribe_category_project_managers()
        return result

    def unlink(self):
        orders = self.mapped('order_id')
        result = super().unlink()
        orders._subscribe_category_project_managers()
        return result
