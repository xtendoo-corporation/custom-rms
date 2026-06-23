# -*- coding: utf-8 -*-

from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    category_product_manager_ids = fields.Many2many(
        comodel_name='res.users',
        related='categ_id.product_manager_ids',
        string='Product Managers',
        readonly=True,
        help='Product managers assigned on this product category.',
    )
