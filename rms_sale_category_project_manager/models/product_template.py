# -*- coding: utf-8 -*-

from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    category_project_manager_ids = fields.Many2many(
        comodel_name='res.users',
        related='categ_id.project_manager_ids',
        string='Project Managers',
        readonly=True,
        help='Project managers assigned on this product category.',
    )
