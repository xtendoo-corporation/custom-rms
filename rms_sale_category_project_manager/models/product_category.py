# -*- coding: utf-8 -*-

from odoo import fields, models


class ProductCategory(models.Model):
    _inherit = 'product.category'

    project_manager_ids = fields.Many2many(
        comodel_name='res.users',
        relation='product_category_project_manager_rel',
        column1='category_id',
        column2='user_id',
        string='Project Managers',
        help='Users automatically added as followers of quotations containing products from this category.',
    )
