# -*- coding: utf-8 -*-
"""Biblioteca versionada de exportaciones; no modifica existencias de Odoo."""
from collections import defaultdict
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from .scan_rule import normalize_code, gtin_variants
from .sage_expected import normalize_serial, sage_article_parts

SAGE_COMPANIES = [('01', 'RMS'), ('02', 'Espacio'), ('03', 'RJB')]
COST_GROUP = 'rms_stock_count_session.group_sage_cost'
BRAND_PREFIXES = {
    'SONY-': 'Sony', 'DIG-': 'DiGiCo', 'DIGX-': 'DiGiCo',
    'DIGCARD-': 'DiGiCo', 'DIGMOD-': 'DiGiCo', 'AUV-': 'Auvitran',
    'W-': 'Whirlwind', 'PS-': 'Point Source', 'LU-': 'Luminex',
    'A-': 'AtlasIED', 'N-': 'Neutrik', 'OPT-': 'Optocore',
    'FUR-': 'Furman', 'WAV-': 'Waves', 'WIL-': 'Williams AV',
    'BLK-': 'BlackTrax', 'SD-': 'Sound Devices', 'TEQ-': 'TEQSAS',
    'HAR-': 'DSPecialists',
}


def article_prefix(article):
    code = article.strip().upper()
    if code.startswith('2M-'):
        code = code[3:]
    elif code.startswith('D-'):
        code = code[2:]
    return code.split('-', 1)[0] + '-' if '-' in code else ''



def article_parts(env, article, prefixes=None):
    model, state = sage_article_parts(article)
    # Las categorías superiores también son prefijos de marca, incluso con espacios.
    if prefixes is None:
        prefixes = sorted(env['product.category'].search([('parent_id', '=', False)]).mapped('name'), key=len, reverse=True)
    for prefix in prefixes:
        parts = model.split('-')
        for pos in range(1, len(parts)):
            if normalize_code('-'.join(parts[:pos])) == normalize_code(prefix):
                return '-'.join(parts[pos:]), state
    return model, state


STOCK_KINDS = [('stock', 'Existencias'), ('deposit', 'Depósitos de venta')]


class SageWarehouse(models.Model):
    _name = 'rms.sage.warehouse'
    _description = 'Almacén de Sage'
    _rec_name = 'name'
    sage_company_code = fields.Selection(SAGE_COMPANIES, required=True, default='01', index=True)
    code = fields.Char(required=True, index=True)
    name = fields.Char(required=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    location_id = fields.Many2one('stock.location', domain="[('usage', '=', 'internal')]", check_company=True)
    _code_unique = models.Constraint('UNIQUE(sage_company_code, code)', 'Ya existe ese almacén en la empresa Sage.')


class SageSnapshot(models.Model):
    _name = 'rms.sage.snapshot'
    _description = 'Exportación de Sage'
    _order = 'export_date desc, id desc'
    name = fields.Char(required=True)
    sage_company_code = fields.Selection(SAGE_COMPANIES, required=True, default='01', index=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    brand_categ_id = fields.Many2one('product.category', required=True, domain="[('parent_id', '=', False)]", index=True)
    export_date = fields.Date(required=True, default=fields.Date.context_today)
    attachment = fields.Binary(attachment=True, groups='stock.group_stock_manager')
    filename = fields.Char()
    file_hash = fields.Char(index=True)
    # La Valoración de Sage (existencias) INCLUYE lo que está en depósito en
    # clientes; los "Depósitos de venta" se cargan aparte para descontarlo.
    stock_kind = fields.Selection(STOCK_KINDS, string='Tipo', required=True, default='stock', index=True)
    state = fields.Selection([('draft', 'Borrador'), ('current', 'Vigente'), ('replaced', 'Reemplazada')], default='draft', required=True, index=True)
    uploaded_by = fields.Many2one('res.users', default=lambda self: self.env.user, readonly=True)
    line_ids = fields.One2many('rms.sage.stock.line', 'snapshot_id')
    line_count = fields.Integer(compute='_compute_totals', store=True, compute_sudo=True)
    unit_count = fields.Float(compute='_compute_totals', store=True, compute_sudo=True)
    unmatched_count = fields.Integer(compute='_compute_totals', store=True, compute_sudo=True)
    total_cost = fields.Float(compute='_compute_totals', store=True, compute_sudo=True, groups=COST_GROUP)
    quality_warnings = fields.Text(readonly=True)
    import_summary = fields.Text(string='Resumen de la carga', readonly=True)

    @api.depends('line_ids.quantity', 'line_ids.cost', 'line_ids.match_state')
    def _compute_totals(self):
        for snapshot in self:
            snapshot.line_count = len(snapshot.line_ids)
            snapshot.unit_count = sum(snapshot.line_ids.mapped('quantity'))
            snapshot.unmatched_count = len(snapshot.line_ids.filtered(lambda l: l.match_state != 'ok'))
            snapshot.total_cost = sum(l.quantity * l.cost for l in snapshot.line_ids)

    def action_activate(self, mode='add', products_resolved=False, whole_company=False):
        """whole_company: el archivo es la empresa completa (todas las marcas).
        Al reemplazar, además de las marcas del archivo, se retiran las marcas
        que venían DEL MISMO archivo anterior y ya no aparecen (p. ej. "Sin
        marca" cuando el maestro de artículos da la marca real). Las marcas
        cargadas aparte con su propio archivo no se tocan."""
        self.check_access('write')
        if any(snapshot.state != 'draft' for snapshot in self):
            raise UserError('Solo se puede activar una exportación en borrador.')
        Line = self.env['rms.sage.stock.line']
        affected = set(self.line_ids.mapped('serial_normalized'))
        retired = self.browse()
        for snapshot in self.sorted(key=lambda snapshot: (snapshot.company_id.id, snapshot.sage_company_code, snapshot.brand_categ_id.id)):
            self.env.cr.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',
                ['rms.sage:%s:%s:%s' % (snapshot.company_id.id, snapshot.sage_company_code, snapshot.brand_categ_id.id)])
            if mode == 'replace':
                retired |= self.search([('id', 'not in', self.ids), ('state', '=', 'current'),
                    ('company_id', '=', snapshot.company_id.id),
                    ('sage_company_code', '=', snapshot.sage_company_code),
                    ('stock_kind', '=', snapshot.stock_kind),
                    ('brand_categ_id', '=', snapshot.brand_categ_id.id)])
        if mode == 'replace' and whole_company:
            # El archivo anterior (de las marcas sustituidas) o el mismo archivo
            # cargado de nuevo.
            hashes = [digest for digest in set(retired.mapped('file_hash') + self.mapped('file_hash')) if digest]
            if hashes:
                retired |= self.search([('id', 'not in', self.ids), ('state', '=', 'current'),
                    ('company_id', 'in', self.company_id.ids),
                    ('sage_company_code', 'in', list(set(self.mapped('sage_company_code')))),
                    ('stock_kind', 'in', list(set(self.mapped('stock_kind')))),
                    ('file_hash', 'in', hashes)])
        if retired:
            affected.update(retired.line_ids.mapped('serial_normalized'))
            retired.line_ids.write({'is_current': False, 'dup_count': 0, 'in_deposit': False})
            retired.write({'state': 'replaced'})
        if not products_resolved:
            self.line_ids._resolve_products()
        self.line_ids.write({'is_current': True})
        self.write({'state': 'current'})
        Line._update_duplicates()
        Line._update_deposits()
        for snapshot in self:
            warnings = []
            if any(line.dup_count > 1 for line in snapshot.line_ids):
                warnings.append('Números de serie duplicados en Sage.')
            if snapshot.unmatched_count:
                warnings.append('%s líneas sin producto resuelto.' % snapshot.unmatched_count)
            if any(line.quantity < 0 for line in snapshot.line_ids):
                warnings.append('Hay depósitos negativos.' if snapshot.stock_kind == 'deposit'
                                else 'Hay existencias negativas.')
            snapshot.quality_warnings = '\n'.join(warnings)
        refresh = getattr(self.env['rms.stock.count.scan'], '_refresh_sage_suggestions', None)
        if refresh:
            refresh(list(affected - {False, ''}))
        return True


class SageStockLine(models.Model):
    _name = 'rms.sage.stock.line'
    _description = 'Existencia global de Sage'
    _order = 'warehouse_code, model_code, serial, id'
    snapshot_id = fields.Many2one('rms.sage.snapshot', required=True, ondelete='cascade', index=True)
    is_current = fields.Boolean(default=False, index=True)
    company_id = fields.Many2one(related='snapshot_id.company_id', store=True, index=True)
    sage_company_code = fields.Selection(related='snapshot_id.sage_company_code', store=True, index=True)
    brand_categ_id = fields.Many2one(related='snapshot_id.brand_categ_id', store=True, index=True)
    stock_kind = fields.Selection(related='snapshot_id.stock_kind', store=True, index=True, string='Tipo')
    in_deposit = fields.Boolean(string='En depósito en cliente', default=False, index=True,
                                help='Sage lo cuenta en existencias pero está en un depósito de venta (en casa de un cliente).')
    warehouse_code = fields.Char(required=True)
    sage_warehouse_id = fields.Many2one('rms.sage.warehouse', index=True)
    article_code = fields.Char(required=True, index=True)
    article_name = fields.Char(string='Nombre en Sage')
    article_normalized = fields.Char(compute='_compute_normalized', store=True, index=True)
    model_code = fields.Char(required=True)
    model_normalized = fields.Char(compute='_compute_normalized', store=True)
    state = fields.Selection([('nuevo', 'Nuevo'), ('demo', 'Demo'), ('2mano', '2ª Mano')], required=True, default='nuevo')
    state_hint = fields.Char(compute='_compute_state_hint')
    serial = fields.Char()
    serial_normalized = fields.Char(compute='_compute_normalized', store=True)
    quantity = fields.Float(default=1)
    cost = fields.Float(groups=COST_GROUP)
    product_id = fields.Many2one('product.product', index=True)
    partner_name = fields.Char(string='Cliente (depósito)',
                               help='Depósitos de venta llegados por Sage en vivo: cliente que tiene el equipo.')
    product_tmpl_id = fields.Many2one(related='product_id.product_tmpl_id', store=True, index=True)
    match_state = fields.Selection([('ok', 'Resuelto'), ('ambiguo', 'Ambiguo'), ('sin_producto', 'Sin producto')], default='sin_producto', index=True)
    dup_count = fields.Integer(default=0)

    def init(self):
        self.env.cr.execute("CREATE INDEX IF NOT EXISTS rms_sage_current_serial_idx ON rms_sage_stock_line(serial_normalized) WHERE is_current AND serial_normalized <> ''")
        self.env.cr.execute('CREATE INDEX IF NOT EXISTS rms_sage_current_model_idx ON rms_sage_stock_line(model_normalized) WHERE is_current')
        self.env.cr.execute('CREATE INDEX IF NOT EXISTS rms_sage_current_scope_idx ON rms_sage_stock_line(sage_company_code, brand_categ_id, warehouse_code) WHERE is_current')

    @api.depends('serial', 'model_code', 'article_code')
    def _compute_normalized(self):
        for line in self:
            line.article_normalized = normalize_code(line.article_code)
            line.serial_normalized = normalize_serial(line.serial)
            line.model_normalized = normalize_code(line.model_code)

    @api.depends('state')
    def _compute_state_hint(self):
        labels = {'nuevo': 'Nuevo', 'demo': 'Demo', '2mano': '2Mano'}
        for line in self:
            line.state_hint = labels.get(line.state, '')

    @api.model
    def _update_duplicates(self):
        self.flush_model()
        # Duplicado = mismo nº de serie y modelo en ubicaciones Sage distintas.
        # Filas idénticas de dos archivos no cuentan doble, y Sony repite nº
        # de serie entre modelos distintos (eso no es un duplicado).
        self.env.cr.execute('''UPDATE rms_sage_stock_line AS l SET dup_count = d.n FROM
            (SELECT serial_normalized, COALESCE(model_normalized, '') AS model,
                    count(DISTINCT COALESCE(sage_company_code, '') || '|' || COALESCE(warehouse_code, '') || '|' || COALESCE(state, '')) AS n
               FROM rms_sage_stock_line
              WHERE is_current AND serial_normalized <> '' AND stock_kind = 'stock' AND quantity > 0 GROUP BY 1, 2) AS d
            WHERE l.is_current AND l.stock_kind = 'stock' AND l.quantity > 0 AND l.serial_normalized = d.serial_normalized
              AND COALESCE(l.model_normalized, '') = d.model''')
        # Los depósitos no son "otra ubicación": no cuentan como duplicado.
        self.env.cr.execute("UPDATE rms_sage_stock_line SET dup_count = 0 WHERE (stock_kind = 'deposit' OR quantity <= 0) AND dup_count <> 0")
        self.invalidate_model(['dup_count'])

    @api.model
    def _update_deposits(self):
        """Marca las existencias vigentes que Sage tiene en un depósito de venta
        (mismo nº de serie y modelo, misma empresa Sage, cantidad positiva)."""
        self.flush_model()
        self.env.cr.execute('''UPDATE rms_sage_stock_line AS l SET in_deposit = (d.serial_normalized IS NOT NULL)
            FROM rms_sage_stock_line AS l2
            LEFT JOIN (SELECT DISTINCT sage_company_code, serial_normalized, COALESCE(model_normalized, '') AS model
                         FROM rms_sage_stock_line
                        WHERE is_current AND stock_kind = 'deposit' AND quantity > 0 AND serial_normalized <> '') AS d
              ON d.sage_company_code = l2.sage_company_code AND d.serial_normalized = l2.serial_normalized
             AND d.model = COALESCE(l2.model_normalized, '')
            WHERE l.id = l2.id AND l.is_current AND l.stock_kind = 'stock'
              AND l.in_deposit IS DISTINCT FROM (d.serial_normalized IS NOT NULL)''')
        self.env.cr.execute("UPDATE rms_sage_stock_line SET in_deposit = false WHERE in_deposit AND (NOT is_current OR stock_kind <> 'stock')")
        self.invalidate_model(['in_deposit'])

    @api.model
    def _resolve_article_values(self, articles, company_id):
        """Resolve each distinct (article, model, state) once using shared indexes.

        Names must be indexed across all brands: Sony stores its model in the
        name while its internal reference is an EAN.
        """
        Product = self.env['product.product'].with_company(company_id)
        indexes = {key: defaultdict(list) for key in ('barcode', 'code', 'normalized', 'name', 'exact_name')}
        root_brand = {}
        for product in Product.search([('company_id', 'in', [False, company_id])]):
            root_brand[product.id] = normalize_code((product.categ_id.complete_name or '').split(' / ')[0])
            for key, value in (('barcode', product.barcode), ('code', product.default_code),
                               ('normalized', normalize_code(product.default_code)),
                               ('name', normalize_code(product.name)), ('exact_name', product.name)):
                if value:
                    indexes[key][value].append(product.id)
        aliases = defaultdict(list)
        for alias in self.env['rms.product.scan.alias'].search([]):
            aliases[alias.code_normalized].extend(alias.product_tmpl_id.product_variant_id.ids)
        maps = self.env['rms.sage.article.map'].search([
            ('article_code', 'in', list({normalize_code(key[0]) for key in articles}))])
        mapped = {mapping.article_code: mapping.product_tmpl_id for mapping in maps}
        prefix_brands = {prefix.upper(): normalize_code(name) for prefix, name in BRAND_PREFIXES.items()}
        for row in self.env['rms.sage.brand.prefix'].search([]):
            prefix = row.prefix.upper() if row.prefix.endswith('-') else row.prefix.upper() + '-'
            prefix_brands[prefix] = normalize_code(row.brand_categ_id.name)
        prefix_brands = sorted(prefix_brands.items(), key=lambda item: len(item[0]), reverse=True)
        result = {}
        for article, model, state in articles:
            template = mapped.get(normalize_code(article))
            if template:
                products = template.product_variant_ids
            else:
                variants, _case = gtin_variants(model)
                ids = list(dict.fromkeys(pid for code in variants for pid in indexes['barcode'].get(code, [])))
                ids = ids or indexes['code'].get(model, [])
                normalized = normalize_code(model)
                if not ids and len(normalized) >= 3:
                    ids = indexes['normalized'].get(normalized, []) or aliases.get(normalized, [])
                ids = ids or indexes['exact_name'].get(model, []) or indexes['name'].get(normalized, [])
                if not ids:
                    # El modelo llega sin el prefijo de marca de Sage, pero algunas
                    # marcas SÍ lo llevan en la referencia de Odoo (Luminex:
                    # Sage LU-01-00058 → modelo 01-00058, Odoo "LU 01 00058").
                    # Se prueba el artículo con prefijo (sin D-/2M-) y solo se
                    # acepta un producto de esa misma marca.
                    full = article.strip().upper()
                    for state_prefix in ('2M-', 'D-'):
                        if full.startswith(state_prefix):
                            full = full[len(state_prefix):]
                    for prefix, brand in prefix_brands:
                        if full.startswith(prefix):
                            key = normalize_code(full)
                            found = indexes['normalized'].get(key, []) or indexes['name'].get(key, [])
                            ids = [pid for pid in found if root_brand.get(pid) == brand]
                            break
                products = Product.browse(list(dict.fromkeys(ids)))
            products = products.filtered(lambda p: not p.company_id or p.company_id.id == company_id)
            if len(products.product_tmpl_id) == 1:
                products = products.product_tmpl_id.product_variant_ids.filtered(
                    lambda p: not p.company_id or p.company_id.id == company_id)
            if len(products) > 1 and len(products.product_tmpl_id) == 1:
                target = {'nuevo': ('NUEVO',), 'demo': ('DEMO',), '2mano': ('2MANO', '2AMANO', 'SEGUNDAMANO')}[state]
                products = products.filtered(lambda p: any(normalize_code(n).replace('ª', '').replace('º', '') in target
                    for n in p.product_template_attribute_value_ids.mapped('name')))
            result[(article, model, state)] = {
                'product_id': products.id if len(products) == 1 else False,
                'match_state': 'ok' if len(products) == 1 else 'ambiguo' if products else 'sin_producto',
            }
        return result

    def _resolve_products(self):
        groups = defaultdict(list)
        for line in self:
            groups[line.company_id.id].append(line)
        warehouses = self.env['rms.sage.warehouse'].search([('sage_company_code', 'in', self.mapped('sage_company_code'))])
        wh_map = {(w.company_id.id, w.sage_company_code, w.code): w.id for w in warehouses}
        for company, lines in groups.items():
            keys = {(line.article_code, line.model_code, line.state) for line in lines}
            resolved = self._resolve_article_values(keys, company)
            writes = defaultdict(list)
            for line in lines:
                vals = resolved[(line.article_code, line.model_code, line.state)]
                warehouse = wh_map.get((company, line.sage_company_code, line.warehouse_code), False)
                writes[(vals['product_id'], vals['match_state'], warehouse)].append(line.id)
            for (product, match, warehouse), ids in writes.items():
                self.browse(ids).write({'product_id': product, 'match_state': match, 'sage_warehouse_id': warehouse})
        return True

    def action_assign_product(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Asignar artículo Sage', 'res_model': 'rms.sage.article.assign', 'view_mode': 'form', 'target': 'new', 'context': {'default_article_code': self.article_code}}


class SageArticleMap(models.Model):
    _name = 'rms.sage.article.map'
    _description = 'Correspondencia artículo Sage y producto'
    article_code = fields.Char(required=True, index=True)
    product_tmpl_id = fields.Many2one('product.template', required=True, ondelete='cascade')
    _article_unique = models.Constraint('UNIQUE(article_code)', 'Ese artículo ya tiene un producto asignado.')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals['article_code'] = normalize_code(vals.get('article_code'))
        return super().create(vals_list)

    def write(self, vals):
        if 'article_code' in vals:
            vals['article_code'] = normalize_code(vals['article_code'])
        return super().write(vals)


class SageArticleAssign(models.TransientModel):
    _name = 'rms.sage.article.assign'
    _description = 'Asignar artículo de Sage'
    article_code = fields.Char(required=True, readonly=True)
    product_tmpl_id = fields.Many2one('product.template', required=True)

    def action_assign(self):
        self.ensure_one()
        code = normalize_code(self.article_code)
        Map = self.env['rms.sage.article.map']
        mapping = Map.search([('article_code', '=', code)], limit=1)
        if mapping:
            mapping.product_tmpl_id = self.product_tmpl_id
        else:
            Map.create({'article_code': code, 'product_tmpl_id': self.product_tmpl_id.id})
        lines = self.env['rms.sage.stock.line'].search([('article_normalized', '=', code)])
        lines._resolve_products()
        refresh = getattr(self.env['rms.stock.count.scan'], '_refresh_sage_suggestions', None)
        if refresh:
            refresh(lines.filtered('is_current').mapped('serial_normalized'))
        return {'type': 'ir.actions.act_window_close'}


class SageBrandPrefix(models.Model):
    _name = 'rms.sage.brand.prefix'
    _description = 'Marca por prefijo de artículo Sage'
    _rec_name = 'prefix'
    _order = 'prefix'

    prefix = fields.Char(required=True, index=True)
    brand_categ_id = fields.Many2one('product.category', required=True,
        domain="[('parent_id', '=', False)]", ondelete='cascade')
    _prefix_unique = models.Constraint('UNIQUE(prefix)', 'Ese prefijo ya tiene una marca asignada.')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals['prefix'] = vals['prefix'].strip().upper().rstrip('-') + '-'
        return super().create(vals_list)

    def write(self, vals):
        if 'prefix' in vals:
            vals['prefix'] = vals['prefix'].strip().upper().rstrip('-') + '-'
        return super().write(vals)

    @api.constrains('prefix', 'brand_categ_id')
    def _check_prefix_brand(self):
        for mapping in self:
            if not mapping.prefix.strip('-').strip():
                raise ValidationError('Indica un prefijo de artículo Sage.')
            if mapping.brand_categ_id.parent_id:
                raise ValidationError('La marca debe ser una categoría de primer nivel.')

    @api.model
    def _seed_existing_brands(self):
        categories = self.env['product.category'].search([('parent_id', '=', False)])
        by_name = {normalize_code(category.name): category.id for category in categories}
        existing = set(self.search([]).mapped('prefix'))
        # These defaults are intentionally restricted to confirmed category names.
        defaults = {prefix: name for prefix, name in BRAND_PREFIXES.items()
                    if name not in ('Waves', 'BlackTrax', 'TEQSAS')}
        vals = [{'prefix': prefix, 'brand_categ_id': by_name[normalize_code(name)]}
                for prefix, name in defaults.items()
                if prefix not in existing and normalize_code(name) in by_name]
        if vals:
            self.create(vals)
