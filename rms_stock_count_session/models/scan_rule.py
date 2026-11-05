# -*- coding: utf-8 -*-

import re

from odoo import api, fields, models
from odoo.exceptions import ValidationError

_NORMALIZE_RE = re.compile(r"[\s\-./_]+")


def normalize_code(code):
    """Forma comparable de una referencia: sin espacios, guiones, puntos ni
    barras y en mayúsculas. Así 'LU 01 00072' (etiqueta Luminex),
    'P-81660762-I' (Sony) o '09.336.001.02' (Meyer) coinciden aunque en Odoo
    se hayan escrito con otro formato."""
    return _NORMALIZE_RE.sub("", code or "").upper()


def _gtin_check_digit(body):
    total = 0
    for i, digit in enumerate(reversed(body)):
        total += int(digit) * (3 if i % 2 == 0 else 1)
    return str((10 - total % 10) % 10)


def gtin_variants(code):
    """Variantes equivalentes de un código EAN/UPC/GTIN para buscarlo en el
    campo 'Código de barras' del producto, y si es un código de caja.

    - UPC-A (12) <-> EAN-13 con 0 delante (AtlasIED, Williams AV, Sound
      Devices llevan UPC y el lector lo puede devolver de las dos formas).
    - GTIN-14/ITF-14 con indicador 1-8 (caja con varias unidades, p. ej. la
      caja de 2 altavoces Atlas FC-4T): se convierte al EAN/UPC de la unidad.
    """
    if not code.isdigit() or len(code) not in (12, 13, 14):
        return [code], False
    variants = [code]
    is_case = False
    if len(code) == 14:
        if code[0] == "0":
            base = code[1:]
        elif code[0] in "12345678":
            is_case = True
            base = code[1:13] + _gtin_check_digit(code[1:13])
        else:
            return variants, False
        variants.append(base)
        code = base
    if len(code) == 12:
        variants.append("0" + code)
    elif len(code) == 13 and code[0] == "0":
        variants.append(code[1:])
    return list(dict.fromkeys(variants)), is_case


class RmsScanRule(models.Model):
    """Reglas para interpretar las etiquetas de cada fabricante. Se aplican
    antes de buscar el código en Odoo: o lo descartan (no es de producto) o
    extraen de él el número de serie."""

    _name = "rms.scan.rule"
    _description = "Regla de lectura de etiquetas"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    name = fields.Char(string="Descripción", required=True)
    brand = fields.Char(string="Marca")
    pattern = fields.Char(
        string="Patrón (expresión regular)",
        required=True,
        help="Se compara con el código completo, sin distinguir mayúsculas. "
             "Para extraer el número de serie, usa un grupo con nombre "
             "(?P<serial>...).",
    )
    action = fields.Selection(
        [("serial", "Es un número de serie"), ("ignore", "Ignorar (no es de producto)")],
        string="Acción", required=True, default="serial",
    )
    transform = fields.Selection(
        [("none", "Ninguna"), ("hex_to_dec", "Hexadecimal a decimal")],
        string="Conversión", required=True, default="none",
        help="Conversión del número de serie extraído (p. ej. el QR de "
             "Auvitran guarda el S/N en hexadecimal).",
    )
    padding = fields.Integer(
        string="Rellenar con ceros hasta",
        help="Longitud mínima del número de serie resultante (0 = sin rellenar).",
    )
    example = fields.Char(string="Ejemplo de lectura")
    note = fields.Text(string="Notas")

    @api.constrains("pattern")
    def _check_pattern(self):
        for rule in self:
            try:
                compiled = re.compile(rule.pattern)
            except re.error as exc:
                raise ValidationError("Patrón no válido en '%s': %s" % (rule.name, exc)) from exc
            if rule.action == "serial" and "serial" not in compiled.groupindex:
                raise ValidationError(
                    "La regla '%s' extrae un número de serie: el patrón necesita "
                    "un grupo (?P<serial>...)." % rule.name
                )

    def _match(self, code):
        """Primera regla que encaja con el código, o None. Devuelve
        {'rule', 'action', 'serial'}."""
        for rule in self.search([]):
            match = re.fullmatch(rule.pattern, code, re.IGNORECASE)
            if not match:
                continue
            serial = False
            if rule.action == "serial":
                serial = match.group("serial")
                if rule.transform == "hex_to_dec":
                    serial = str(int(serial, 16))
                if rule.padding:
                    serial = serial.zfill(rule.padding)
            return {"rule": rule, "action": rule.action, "serial": serial}
        return None


class RmsProductScanAlias(models.Model):
    """Otros códigos que identifican un producto: referencias del fabricante
    impresas en la caja (con o sin código de barras), códigos de la etiqueta
    del ERP anterior, etc. Se comparan normalizados (sin espacios, guiones
    ni puntos)."""

    _name = "rms.product.scan.alias"
    _description = "Código alternativo de producto"
    _order = "product_tmpl_id, id"

    product_tmpl_id = fields.Many2one(
        "product.template", string="Producto", required=True, ondelete="cascade", index=True,
    )
    code = fields.Char(string="Código", required=True)
    code_normalized = fields.Char(compute="_compute_code_normalized", store=True, index=True)
    note = fields.Char(string="Origen", help="P. ej. 'Part number de la caja DiGiCo'.")

    _code_uniq = models.Constraint(
        "UNIQUE(product_tmpl_id, code_normalized)",
        "Ese código ya está registrado para este producto.",
    )

    @api.depends("code")
    def _compute_code_normalized(self):
        for alias in self:
            alias.code_normalized = normalize_code(alias.code)


class ProductTemplate(models.Model):
    _inherit = "product.template"

    rms_scan_alias_ids = fields.One2many(
        "rms.product.scan.alias", "product_tmpl_id", string="Códigos alternativos de escaneo",
    )


class ProductProduct(models.Model):
    _inherit = "product.product"

    rms_default_code_normalized = fields.Char(
        compute="_compute_rms_default_code_normalized", store=True, index=True,
    )

    @api.depends("default_code")
    def _compute_rms_default_code_normalized(self):
        for product in self:
            product.rms_default_code_normalized = normalize_code(product.default_code) or False

    @api.model
    def _rms_find_by_code(self, code):
        """Busca el producto de un código escaneado. Devuelve (productos,
        es_caja): por código de barras (con variantes EAN/UPC/ITF-14), por
        referencia interna (exacta o normalizada) o por código alternativo."""
        variants, is_case = gtin_variants(code)
        products = self.search([("barcode", "in", variants)], limit=2)
        if products:
            return products, is_case
        products = self.search([("default_code", "=", code)], limit=2)
        if products:
            return products, False
        normalized = normalize_code(code)
        if len(normalized) < 3:
            return self.browse(), False
        products = self.search([("rms_default_code_normalized", "=", normalized)], limit=2)
        if products:
            return products, False
        aliases = self.env["rms.product.scan.alias"].search(
            [("code_normalized", "=", normalized)], limit=2
        )
        return aliases.product_tmpl_id.product_variant_id, False
