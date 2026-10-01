# -*- coding: utf-8 -*-

from odoo import api, fields, models


class ProductCategory(models.Model):
    _inherit = 'product.category'

    hide_from_comerciales = fields.Boolean(
        string='Ocultar a comerciales',
        help='Los productos de esta categoría (y de sus subcategorías) no serán '
             'visibles para los usuarios del grupo Comerciales.',
    )
    hide_from_comerciales_effective = fields.Boolean(
        string='Oculto a comerciales (heredado)',
        compute='_compute_hide_from_comerciales_effective',
        recursive=True,
        store=True,
    )

    @api.depends('hide_from_comerciales', 'parent_id.hide_from_comerciales_effective')
    def _compute_hide_from_comerciales_effective(self):
        for categ in self:
            categ.hide_from_comerciales_effective = (
                categ.hide_from_comerciales
                or bool(categ.parent_id.hide_from_comerciales_effective)
            )
