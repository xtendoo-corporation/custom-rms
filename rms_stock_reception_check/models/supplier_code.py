# -*- coding: utf-8 -*-
from odoo import api, fields, models

from odoo.addons.rms_stock_count_session.models.scan_rule import normalize_code


class RmsReceptionSupplierCode(models.Model):
    """Código con el que un proveedor llama a un producto en sus facturas.
    Se aprende solo: cuando alguien asigna a mano el producto en la vista
    previa del documento, la próxima vez ya sale asignado."""

    _name = "rms.reception.supplier.code"
    _description = "Código de proveedor"
    _order = "partner_id, code"
    _rec_name = "code"

    partner_id = fields.Many2one(
        "res.partner", string="Proveedor", required=True, ondelete="cascade", index=True,
    )
    code = fields.Char(string="Código del proveedor", required=True)
    code_normalized = fields.Char(compute="_compute_code_normalized", store=True, index=True)
    product_id = fields.Many2one(
        "product.product", string="Producto", required=True, ondelete="cascade", index=True,
    )
    note = fields.Char(string="Origen")

    _partner_code_uniq = models.Constraint(
        "UNIQUE(partner_id, code_normalized)",
        "Ese código ya está registrado para este proveedor.",
    )

    @api.depends("code")
    def _compute_code_normalized(self):
        for record in self:
            record.code_normalized = normalize_code(record.code)

    @api.model
    def _find_product(self, partner, code):
        """Producto de un código de proveedor. Devuelve (producto, origen):
        origen = 'learned' (tabla propia), 'odoo' (referencia interna, código
        de barras o código alternativo) o False."""
        Product = self.env["product.product"]
        code = (code or "").strip()
        normalized = normalize_code(code)
        if not normalized:
            return Product, False
        if partner:
            learned = self.search([
                ("partner_id", "=", partner.commercial_partner_id.id),
                ("code_normalized", "=", normalized),
            ], limit=1)
            if learned:
                return learned.product_id, "learned"
        products, _is_case = Product._rms_find_by_code(code)
        if len(products) > 1 and len(products.product_tmpl_id) == 1:
            products = products[:1]
        if len(products) == 1:
            return products, "odoo"
        return Product, False

    @api.model
    def _learn(self, partner, code, product):
        """Recuerda que este proveedor llama `code` a `product`."""
        normalized = normalize_code(code)
        if not partner or not normalized or not product:
            return self.browse()
        partner = partner.commercial_partner_id
        existing = self.search([
            ("partner_id", "=", partner.id), ("code_normalized", "=", normalized),
        ], limit=1)
        if existing:
            if existing.product_id != product:
                existing.product_id = product.id
            return existing
        return self.create({
            "partner_id": partner.id, "code": code.strip(), "product_id": product.id,
            "note": "Aprendido al cargar un documento",
        })
