# -*- coding: utf-8 -*-
"""Existencias de Sage conservadas como referencia, sin modificar stock Odoo."""
from collections import defaultdict

from odoo import api, fields, models
from odoo.exceptions import UserError

from .scan_rule import normalize_code


def normalize_serial(value):
    compact = normalize_code(str(value or ''))
    return (compact.lstrip('0') or '0') if compact else ''


def serial_alternatives(key):
    """Otras formas del mismo nº de serie ya normalizado, por si la etiqueta
    y Sage no coinciden: AtlasIED guarda "SN" delante en Sage y no siempre en
    la etiqueta (y al revés; "S/N:" se normaliza también a "SN")."""
    if not key:
        return []
    if key.startswith('SN') and len(key) > 4:
        rest = key[2:].lstrip('0') or '0'
        return [rest]
    return ['SN' + key]


def sage_article_parts(article):
    article = article.strip()
    state = 'Nuevo'
    if article.upper().startswith('2M-'):
        state, article = '2Mano', article[3:]
    elif article.upper().startswith('D-'):
        state, article = 'Demo', article[2:]
    # Sage antepone la marca al modelo. No cortar WD-850A ni DWM-02N.
    brands = ('SONY', 'DIGICO', 'MEYER', 'LUMINEX', 'AUVITRAN', 'ATLASIED',
              'WILLIAMS', 'SOUNDDEVICES', 'SENNHEISER', 'SHURE', 'YAMAHA',
              'DIG', 'DIGX', 'DIGCARD', 'DIGMOD', 'AUV', 'W', 'PS', 'LU',
              'A', 'N', 'OPT', 'FUR', 'WAV', 'WIL', 'BLK', 'SD', 'TEQ', 'HAR')
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
    cost = fields.Float(string='Precio', groups='rms_stock_count_session.group_sage_cost')
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
                    products = Product.search([('name', '=', line.model_code), ('company_id', 'in', [False, key[0]])], limit=3)
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
    stock_line_id = fields.Many2one('rms.sage.stock.line', ondelete='set null', index=True)
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

    sage_company_code = fields.Selection([('01', 'RMS'), ('02', 'Espacio'), ('03', 'RJB')], default='01', required=True)
    brand_categ_ids = fields.Many2many('product.category', string='Marcas Sage', domain="[('parent_id', '=', False)]")
    sage_warehouse_ids = fields.Many2many('rms.sage.warehouse', string='Almacenes Sage')
    sage_mode = fields.Selection([
        ('global', 'Checklist global de Sage'),
        ('scope', 'Solo empresa, marcas y almacenes de este recuento'),
    ], string='Comparar con Sage', default='global', required=True,
        help="Checklist global: cada nº de serie se busca en todo Sage (las 3 "
             "empresas y todos los almacenes) y se pone en verde si está, "
             "diga donde diga. Alcance: solo cuenta como 'aquí' lo de la "
             "empresa, marcas y almacenes elegidos.")

    @api.onchange('location_id', 'company_id', 'sage_company_code')
    def _onchange_sage_scope(self):
        for session in self:
            session.sage_warehouse_ids = self.env['rms.sage.warehouse'].search([
                ('company_id', '=', session.company_id.id),
                ('sage_company_code', '=', session.sage_company_code),
                ('location_id', '=', session.location_id.id),
            ])

    @api.model_create_multi
    def create(self, vals_list):
        sessions = super().create(vals_list)
        for session, vals in zip(sessions, vals_list):
            if 'sage_warehouse_ids' not in vals:
                session._onchange_sage_scope()
        return sessions

    def _sage_scope_domain(self):
        self.ensure_one()
        # Solo existencias: los depósitos de venta se cargan aparte para descontar.
        return [('is_current', '=', True), ('stock_kind', '=', 'stock'), ('company_id', '=', self.company_id.id),
                ('sage_company_code', '=', self.sage_company_code),
                ('brand_categ_id', 'in', self.brand_categ_ids.ids),
                ('sage_warehouse_id', 'in', self.sage_warehouse_ids.ids)]

    def _sage_lines(self):
        """Lo que se espera encontrar en la zona: sin lo que Sage tiene en
        depósito en casa de un cliente."""
        return self.env['rms.sage.stock.line'].sudo().search(self._sage_scope_domain() + [('in_deposit', '=', False)])

    expected_ids = fields.One2many('rms.stock.count.expected', 'session_id', string='Exportación Sage')
    sage_line_ids = fields.One2many('rms.stock.count.sage.line', 'session_id', string='Cruce Sage')
    sage_expected_count = fields.Integer(compute='_compute_sage_count', groups='stock.group_stock_manager')

    def _compute_sage_count(self):
        for session in self:
            session.sage_expected_count = len(session._sage_lines())

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
            # Índices por nº de serie y por producto: sin recorrer 'remaining'
            # entero por cada línea de Sage (cuadrático con miles de líneas).
            by_serial, by_product = {}, {}
            for rkey in remaining:
                by_serial.setdefault(rkey[1], []).append(rkey)
                by_product.setdefault(rkey[0], []).append(rkey)
            vals = []
            for expected in session._sage_lines().sorted(key=lambda e: (not bool(e.serial), e.id)):
                serial = expected.serial_normalized or ''
                key = (expected.product_id.id, serial)
                matches = [key] if expected.product_id and remaining.get(key, 0) > 0 else []
                if not matches and serial:
                    matches = [k for k in by_serial.get(serial, []) if remaining[k] > 0]
                if not serial and expected.product_id:
                    matches = [k for k in by_product.get(expected.product_id.id, []) if remaining[k] > 0]
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
                    'session_id': session.id, 'stock_line_id': expected.id,
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
        if not self.env.user.has_group('stock.group_stock_manager'):
            raise UserError('Solo administración puede consultar el cruce de Sage.')
        self._build_sage_reconciliation()
        return {'type': 'ir.actions.act_window', 'name': 'Cruce Sage',
                'res_model': 'rms.stock.count.sage.line', 'view_mode': 'list',
                'domain': [('session_id', '=', self.id)], 'context': {'create': False}}
