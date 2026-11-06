# -*- coding: utf-8 -*-
"""Existencias de Sage conservadas como referencia, sin modificar stock Odoo."""
from collections import defaultdict

from odoo import api, fields, models
from odoo.exceptions import UserError

from .scan_rule import normalize_code


def normalize_serial(value):
    compact = normalize_code(str(value or ''))
    return (compact.lstrip('0') or '0') if compact else ''


def sage_article_parts(article):
    article = article.strip()
    state = 'Nuevo'
    if article.upper().startswith('2M-'):
        state, article = '2Mano', article[3:]
    elif article.upper().startswith('D-'):
        state, article = 'Demo', article[2:]
    # Sage antepone la marca al modelo. No cortar WD-850A ni DWM-02N.
    brands = ('SONY', 'DIGICO', 'MEYER', 'LUMINEX', 'AUVITRAN', 'ATLASIED',
              'WILLIAMS', 'SOUNDDEVICES', 'SENNHEISER', 'SHURE', 'YAMAHA')
    for brand in brands:
        if article.upper().startswith(brand + '-'):
            article = article[len(brand) + 1:]
            break
    return article, state


class StockCountExpected(models.Model):
    _name = 'rms.stock.count.expected'
    _description = 'Existencia esperada de Sage'
    _order = 'warehouse_code, article_code, serial, id'

    session_id = fields.Many2one('rms.stock.count.session', required=True, ondelete='cascade', index=True)
    warehouse_code = fields.Char(string='Almacén Sage', required=True, index=True)
    article_code = fields.Char(string='Artículo Sage', required=True)
    model_code = fields.Char(string='Modelo', required=True)
    state_hint = fields.Char(string='Estado Sage')
    serial = fields.Char(string='Número de serie')
    serial_normalized = fields.Char(compute='_compute_serial', store=True, index=True)
    quantity = fields.Float(string='Unidades', default=1)
    cost = fields.Float(string='Precio')
    product_id = fields.Many2one('product.product', compute='_compute_product', store=True, string='Producto')

    @api.depends('serial')
    def _compute_serial(self):
        for line in self:
            line.serial_normalized = normalize_serial(line.serial)

    @api.depends('model_code', 'state_hint', 'session_id.company_id')
    def _compute_product(self):
        cache = {}
        for line in self:
            key = (line.session_id.company_id.id, normalize_code(line.model_code), line.state_hint)
            if key not in cache:
                Product = self.env['product.product'].with_company(line.session_id.company_id)
                products, _case = Product._rms_find_by_code(line.model_code or '')
                if not products:
                    products = Product.search([
                        ('company_id', 'in', [False, key[0]]),
                    ]).filtered(lambda p: normalize_code(p.name) == key[1]
                                or normalize_code(p.barcode) == key[1])
                if len(products.product_tmpl_id) == 1:
                    products = products.product_tmpl_id.product_variant_ids
                products = products.filtered(lambda p: not p.company_id or p.company_id.id == key[0])
                if len(products) > 1 and len(products.product_tmpl_id) == 1:
                    state = normalize_code(line.state_hint).replace('ª', '').replace('º', '')
                    def matches_state(product):
                        names = product.product_template_attribute_value_ids.mapped('name')
                        names = [normalize_code(n).replace('ª', '').replace('º', '') for n in names]
                        if state == '2MANO':
                            return any(n in ('2MANO', '2AMANO', 'SEGUNDAMANO') for n in names)
                        return state in names
                    products = products.filtered(matches_state)
                cache[key] = products if len(products) == 1 else Product.browse()
            line.product_id = cache[key]


class StockCountSageLine(models.Model):
    _name = 'rms.stock.count.sage.line'
    _description = 'Cruce de recuento con Sage'
    _order = 'status, warehouse_code, article_code, id'

    session_id = fields.Many2one('rms.stock.count.session', required=True, ondelete='cascade', index=True)
    expected_id = fields.Many2one('rms.stock.count.expected', ondelete='cascade')
    warehouse_code = fields.Char(string='Almacén Sage', index=True)
    article_code = fields.Char(string='Artículo Sage')
    state_hint = fields.Char(string='Estado Sage')
    serial = fields.Char(string='Número de serie')
    product_id = fields.Many2one('product.product', string='Producto esperado')
    counted_product_id = fields.Many2one('product.product', string='Producto contado')
    expected_qty = fields.Float(string='Unidades Sage')
    counted_qty = fields.Float(string='Unidades contadas')
    status = fields.Selection([
        ('counted', 'contado aquí'), ('wrong_product', 'contado con otro producto'),
        ('missing', 'no contado'), ('unexpected', 'sobra (no está en Sage)'),
    ], required=True, string='Resultado', index=True)


class StockCountSession(models.Model):
    _inherit = 'rms.stock.count.session'

    expected_ids = fields.One2many('rms.stock.count.expected', 'session_id', string='Exportación Sage')
    sage_line_ids = fields.One2many('rms.stock.count.sage.line', 'session_id', string='Cruce Sage')
    sage_expected_count = fields.Integer(compute='_compute_sage_count')

    @api.depends('expected_ids')
    def _compute_sage_count(self):
        for session in self:
            session.sage_expected_count = len(session.expected_ids)

    def action_import_sage(self):
        self.ensure_one()
        if self.state in ('done', 'cancel'):
            raise UserError('El recuento está cerrado.')
        return {'type': 'ir.actions.act_window', 'name': 'Cargar exportación de Sage',
                'res_model': 'rms.stock.count.sage.import', 'view_mode': 'form', 'target': 'new',
                'context': {'default_session_id': self.id}}

    def _build_sage_reconciliation(self):
        """Una unidad vista por varios operarios se cuenta una sola vez."""
        for session in self:
            session.sage_line_ids.unlink()
            per_operator = defaultdict(lambda: defaultdict(float))
            serial_names = {}
            serial_products = set()
            for scan in session.scan_ids.filtered(
                lambda s: not s.ignored and s.scan_type in ('serial', 'product') and s.product_id
            ):
                key = (scan.product_id.id, normalize_serial(scan.lot_name))
                per_operator[key][scan.operator_id.id] += scan.quantity
                serial_names[key] = scan.lot_name
                if scan.product_id.tracking == 'serial':
                    serial_products.add(scan.product_id.id)
            remaining = {key: (1.0 if key[1] and key[0] in serial_products else max(qtys.values()))
                         for key, qtys in per_operator.items()}
            vals = []
            for expected in session.expected_ids.sorted(key=lambda e: (not bool(e.serial), e.id)):
                serial = expected.serial_normalized or ''
                key = (expected.product_id.id, serial)
                matches = [key] if expected.product_id and remaining.get(key, 0) > 0 else []
                if not matches and serial:
                    matches = [k for k, qty in remaining.items() if k[1] == serial and qty > 0]
                if not serial and expected.product_id:
                    matches = [k for k, qty in remaining.items()
                               if k[0] == expected.product_id.id and qty > 0]
                counted = 0
                counted_product = False
                for matched in matches:
                    quantity = min(max(0, expected.quantity - counted), remaining[matched])
                    remaining[matched] -= quantity
                    counted += quantity
                    if quantity:
                        counted_product = matched[0]
                    if counted >= expected.quantity:
                        break
                vals.append({
                    'session_id': session.id, 'expected_id': expected.id,
                    'warehouse_code': expected.warehouse_code, 'article_code': expected.article_code,
                    'state_hint': expected.state_hint, 'serial': expected.serial,
                    'product_id': expected.product_id.id, 'counted_product_id': counted_product,
                    'expected_qty': expected.quantity, 'counted_qty': counted,
                    'status': ('wrong_product' if counted and counted_product != expected.product_id.id
                               else 'counted' if counted >= expected.quantity and counted > 0
                               else 'missing'),
                })
            for (product_id, serial), quantity in remaining.items():
                if quantity > 0:
                    vals.append({'session_id': session.id, 'product_id': product_id,
                                 'counted_product_id': product_id, 'serial': serial_names.get((product_id, serial)),
                                 'counted_qty': quantity, 'status': 'unexpected'})
            self.env['rms.stock.count.sage.line'].create(vals)

    def action_view_sage(self):
        self.ensure_one()
        self.expected_ids._compute_product()
        self._build_sage_reconciliation()
        return {'type': 'ir.actions.act_window', 'name': 'Cruce Sage',
                'res_model': 'rms.stock.count.sage.line', 'view_mode': 'list',
                'domain': [('session_id', '=', self.id)], 'context': {'create': False}}
