# -*- coding: utf-8 -*-

from odoo import models, fields, api

class ProductAttributeValue(models.Model):
    _inherit = 'product.attribute.value'

    color = fields.Integer(
        string="Color Index",
        compute="_compute_color",
        store=True,
        readonly=False,
    )

    @api.depends('name')
    def _compute_color(self):
        for record in self:
            name_lower = (record.name or '').lower()
            if 'nuevo' in name_lower:
                record.color = 10  # Green
            elif '2 mano' in name_lower:
                record.color = 3   # Yellow
            elif 'demo' in name_lower:
                record.color = 2   # Orange
            else:
                record.color = 0   # Grey / No color (Neutral)

    def init(self):
        # Los colores existentes se actualizan una sola vez mediante migración.
        super().init()


class ProductTemplateAttributeValue(models.Model):
    _inherit = 'product.template.attribute.value'

    color = fields.Integer(
        string="Color",
        compute="_compute_color",
        store=True,
        readonly=False,
    )

    @api.depends('product_attribute_value_id.color')
    def _compute_color(self):
        for record in self:
            record.color = record.product_attribute_value_id.color or 0



