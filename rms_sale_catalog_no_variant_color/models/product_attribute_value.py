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
        """
        Runs during module upgrade/installation to instantly update the colors
        of all existing records in the database.
        """
        super().init()
        # Actualiza product.attribute.value buscando en cualquier idioma/traducción (JSONB en Odoo 17+)
        self.env.cr.execute("""
            UPDATE product_attribute_value
            SET color = CASE 
                WHEN name::text ILIKE '%nuevo%' THEN 10
                WHEN name::text ILIKE '%2 mano%' THEN 3
                WHEN name::text ILIKE '%demo%' THEN 2
                ELSE 0
            END;
        """)
        # Sincroniza product.template.attribute.value
        self.env.cr.execute("""
            UPDATE product_template_attribute_value ptav
            SET color = pav.color
            FROM product_attribute_value pav
            WHERE ptav.product_attribute_value_id = pav.id;
        """)


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



