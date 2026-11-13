# -*- coding: utf-8 -*-
"""Maestro de artículos de Sage (común a las 3 empresas): marca, familia,
subfamilia y baja de cada código. Sirve para dar a cada línea de existencias
su marca real (antes se deducía del prefijo y salían muchos "Sin marca") y
para crear los productos con su nombre y marca."""
import re
from collections import defaultdict

from odoo import api, fields, models

from .scan_rule import normalize_code


class SageArticle(models.Model):
    _name = 'rms.sage.article'
    _description = 'Artículo del maestro de Sage'
    _order = 'code'
    _rec_name = 'code'

    code = fields.Char(string='Código', required=True, index=True)
    code_normalized = fields.Char(compute='_compute_code_normalized', store=True, index=True)
    name = fields.Char(string='Nombre')
    brand_code = fields.Char(string='Marca')
    brand_name = fields.Char(string='Nombre marca', index=True)
    family_code = fields.Char(string='Familia', index=True)
    family_name = fields.Char(string='Nombre familia')
    subfamily_code = fields.Char(string='Subfamilia')
    subfamily_name = fields.Char(string='Nombre subfamilia')
    discontinued = fields.Boolean(string='De baja en Sage')
    discontinued_date = fields.Char(string='Fecha de baja')
    state_prefix = fields.Selection([('nuevo', 'Sin prefijo'), ('demo', 'D- (Demo / Ex-Demo)'),
                                     ('2mano', '2M- (2ª mano)')],
                                    compute='_compute_code_normalized', store=True, string='Prefijo de estado')
    brand_categ_id = fields.Many2one('product.category', string='Marca en Odoo',
                                     domain="[('parent_id', '=', False)]")

    _code_unique = models.Constraint('UNIQUE(code)', 'Ese código ya está en el maestro de Sage.')

    @api.depends('code')
    def _compute_code_normalized(self):
        for article in self:
            code = (article.code or '').strip().upper()
            article.code_normalized = normalize_code(code)
            article.state_prefix = ('2mano' if code.startswith('2M-') else
                                    'demo' if code.startswith(('D-', 'DEMO-')) or re.search(r'[-. ]DEMO$', code)
                                    else 'nuevo')

    @api.model
    def _brand_categories(self, brand_names, create=True):
        """Categoría de primer nivel de Odoo para cada nombre de marca de Sage
        (comparando sin espacios ni mayúsculas: "MEYER SOUND" = "Meyer Sound",
        "WILLIAMSAV" = "Williams AV", "HARVEY" = "DSPecialists (Harvey)").
        Las que no existen se crean."""
        Category = self.env['product.category'].sudo()
        roots = {}
        top = Category.search([('parent_id', '=', False)], order='id')
        for category in top:
            # "DSPecialists (Harvey)" también responde a "HARVEY".
            for alias in re.findall(r'\(([^)]*)\)', category.name or ''):
                roots.setdefault(normalize_code(alias), category)
        for category in top:
            roots[normalize_code(category.name)] = category
        result = {}
        for name in {n for n in brand_names if n}:
            key = normalize_code(name)
            if key not in roots and create:
                roots[key] = Category.create({'name': name.strip().title() if name.isupper() else name.strip()})
            if key in roots:
                result[name] = roots[key]
        return result

    @api.model
    def _brands_by_article(self, article_codes):
        """{código de artículo normalizado: categoría de marca} según el maestro."""
        keys = list({normalize_code(code) for code in article_codes if code})
        if not keys:
            return {}
        articles = self.search([('code_normalized', 'in', keys)])
        missing = articles.filtered(lambda a: not a.brand_categ_id and a.brand_name)
        if missing:
            categories = self._brand_categories(missing.mapped('brand_name'))
            by_brand = defaultdict(lambda: self.browse())
            for article in missing:
                by_brand[article.brand_name] |= article
            for brand_name, group in by_brand.items():
                if brand_name in categories:
                    group.write({'brand_categ_id': categories[brand_name].id})
        return {article.code_normalized: article.brand_categ_id.id
                for article in articles if article.brand_categ_id}
