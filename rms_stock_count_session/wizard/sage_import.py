# -*- coding: utf-8 -*-
import base64
import binascii
import csv
import hashlib
from collections import Counter, defaultdict
from io import BytesIO, StringIO
from zipfile import BadZipFile

from odoo import fields, models
from odoo.exceptions import AccessError, UserError

from ..models.sage_expected import normalize_serial
from ..models.scan_rule import normalize_code

from ..models.sage_library import SAGE_COMPANIES, article_parts, article_prefix


class StockCountSageImport(models.TransientModel):
    _name = 'rms.stock.count.sage.import'
    _description = 'Cargar exportación de Sage'

    session_id = fields.Many2one('rms.stock.count.session', ondelete='cascade')
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    sage_company_code = fields.Selection(SAGE_COMPANIES, required=True, default='01')
    scope = fields.Selection([('all', 'Todas las marcas (archivo completo de la empresa)'),
                              ('brand', 'Una marca')], required=True, default='all')
    brand_categ_id = fields.Many2one('product.category', domain="[('parent_id', '=', False)]")
    mode = fields.Selection([('add', 'Añadir archivos'), ('replace', 'Reemplazar versión')], required=True, default='replace')
    export_date = fields.Date(required=True, default=fields.Date.context_today)
    file_data = fields.Binary(string='Excel o CSV Valoración de stocks', required=True)
    filename = fields.Char(string='Nombre de archivo')
    parse_warnings = fields.Text(readonly=True)
    allow_duplicate = fields.Boolean(string='Cargar aunque ya se haya cargado este archivo')

    def action_import(self):
        self.ensure_one()
        self.check_access('write')
        if not self.env.user.has_group('stock.group_stock_manager'):
            raise AccessError('Solo administración de inventario puede cargar Sage.')
        if self.company_id not in self.env.companies:
            raise AccessError('La empresa no está permitida.')
        if self.scope == 'brand' and not self.brand_categ_id:
            raise UserError('Selecciona una marca para cargar un archivo de una marca.')
        if self.scope == 'brand' and self.brand_categ_id.parent_id:
            raise UserError('La marca debe ser una categoría de primer nivel.')
        try:
            raw = base64.b64decode(self.file_data, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise UserError('El archivo no es válido.') from exc
        digest = hashlib.sha256(raw).hexdigest()
        Snapshot = self.env['rms.sage.snapshot']
        workbook = None
        try:
            if (self.filename or '').lower().endswith('.csv') or not raw.startswith(b'PK'):
                try:
                    content = raw.decode('utf-8-sig')
                except UnicodeDecodeError:
                    content = raw.decode('latin-1')
                try:
                    dialect = csv.Sniffer().sniff(content[:8192], delimiters=';,')
                    rows = csv.reader(StringIO(content, newline=""), dialect)
                except csv.Error:
                    rows = csv.reader(StringIO(content, newline=""), delimiter=';')
            else:
                from openpyxl import load_workbook
                workbook = load_workbook(BytesIO(raw), read_only=True, data_only=True)
                rows = workbook.active.iter_rows(values_only=True)
            vals = self._parse_rows(rows)
        except (ValueError, TypeError, OSError, KeyError, BadZipFile) as exc:
            raise UserError('No se puede leer la exportación de Sage: %s' % exc) from exc
        finally:
            if workbook:
                workbook.close()
        if not vals:
            raise UserError('La exportación no contiene existencias.')
        Line = self.env['rms.sage.stock.line'].sudo().with_context(tracking_disable=True, mail_notrack=True)
        for val in vals:
            val.pop('session_id', None)
            hint = val.pop('state_hint', 'Nuevo')
            val['state'] = {'Nuevo': 'nuevo', 'Demo': 'demo', '2Mano': '2mano'}.get(hint, 'nuevo')
        articles = {(val['article_code'], val['model_code'], val['state']) for val in vals}
        resolved = Line._resolve_article_values(articles, self.company_id.id)
        products = self.env['product.product'].browse(list({v['product_id'] for v in resolved.values() if v['product_id']}))
        product_brands = {}
        for product in products:
            category = product.categ_id
            while category.parent_id:
                category = category.parent_id
            product_brands[product.id] = category.id
        # Count articles, not stock rows or serials, when learning prefixes and
        # detecting a company-wide file uploaded as a single brand.
        counts = Counter()
        learned = defaultdict(Counter)
        seen_articles = set()
        for key, match in resolved.items():
            article = normalize_code(key[0])
            brand = product_brands.get(match['product_id'])
            if brand and article not in seen_articles:
                seen_articles.add(article)
                counts[brand] += 1
                prefix = article_prefix(key[0])
                if prefix:
                    learned[prefix][brand] += 1
        if self.scope == 'brand' and counts:
            other = sum(count for brand, count in counts.items() if brand != self.brand_categ_id.id)
            if other / sum(counts.values()) > 0.20:
                categories = self.env['product.category'].browse(sorted(counts))
                details = ', '.join('%s de %s' % (counts[category.id], category.name) for category in categories)
                raise UserError("Este archivo parece tener varias marcas (%s); elige 'Todas las marcas'" % details)
        prefix_brands = {}
        if self.scope == 'all':
            Prefix = self.env['rms.sage.brand.prefix']
            Prefix._seed_existing_brands()
            prefix_brands = {mapping.prefix: mapping.brand_categ_id.id for mapping in Prefix.search([])
                             if not mapping.brand_categ_id.parent_id}
            for prefix, brands in learned.items():
                prefix_brands[prefix] = min(brands, key=lambda brand: (-brands[brand], brand))
        # Marca según el maestro de artículos de Sage (si se ha cargado).
        master_brands = {}
        if self.scope == 'all':
            master_brands = self.env['rms.sage.article'].sudo()._brands_by_article(
                {val['article_code'] for val in vals})
        grouped = defaultdict(list)
        unknown = False
        warehouses = self.env['rms.sage.warehouse'].search([
            ('company_id', '=', self.company_id.id), ('sage_company_code', '=', self.sage_company_code)])
        wh_map = {warehouse.code: warehouse.id for warehouse in warehouses}
        for val in vals:
            match = resolved[(val['article_code'], val['model_code'], val['state'])]
            val.update(match, sage_warehouse_id=wh_map.get(val['warehouse_code'], False))
            brand = self.brand_categ_id.id if self.scope == 'brand' else (
                product_brands.get(match['product_id'])
                or master_brands.get(normalize_code(val['article_code']))
                or prefix_brands.get(article_prefix(val['article_code'])))
            if not brand:
                if not unknown:
                    Category = self.env['product.category'].sudo()
                    unknown = Category.search([('name', '=', 'Sin marca'), ('parent_id', '=', False)], limit=1)
                    if not unknown:
                        unknown = Category.create({'name': 'Sin marca'})
                brand = unknown.id
            grouped[brand].append(val)
        domain = [('file_hash', '=', digest), ('company_id', '=', self.company_id.id),
                  ('sage_company_code', '=', self.sage_company_code), ('brand_categ_id', 'in', list(grouped))]
        if not self.allow_duplicate and Snapshot.search_count(domain):
            raise UserError('Este archivo ya se cargó. Activa «Cargar aunque ya se haya cargado» para continuar.')
        snapshots = Snapshot.with_context(tracking_disable=True, mail_notrack=True).create([
            {'name': self.filename or 'Exportación Sage', 'company_id': self.company_id.id,
             'sage_company_code': self.sage_company_code, 'brand_categ_id': brand,
             'export_date': self.export_date, 'filename': self.filename,
             'attachment': self.file_data, 'file_hash': digest} for brand in sorted(grouped)])
        # Binary attachment storage deduplicates the identical file content.
        summary = []
        for snapshot in snapshots:
            values = grouped[snapshot.brand_categ_id.id]
            for val in values:
                val['snapshot_id'] = snapshot.id
            for start in range(0, len(values), 2000):
                Line.create(values[start:start + 2000])
            summary.append('%s: %s líneas, %s unidades, %s números de serie, %s sin producto.' % (
                snapshot.brand_categ_id.name, len(values), sum(val['quantity'] for val in values),
                sum(bool(val.get('serial')) for val in values), sum(val['match_state'] != 'ok' for val in values)))
        snapshots.action_activate(self.mode, products_resolved=True)
        for snapshot in snapshots:
            snapshot.quality_warnings = '\n'.join(filter(None, [snapshot.quality_warnings, self.parse_warnings]))
        message = '\n'.join(summary)
        # Keep the per-brand summary available after the notification disappears.
        snapshots.write({'import_summary': message})
        # 'views' es obligatorio: la acción 'next' de la notificación la abre
        # el cliente tal cual y Odoo 19 falla sin ella ("action.views is undefined").
        action = {'type': 'ir.actions.act_window', 'name': 'Carpeta Sage', 'res_model': 'rms.sage.snapshot',
                  'view_mode': 'list,form', 'views': [(False, 'list'), (False, 'form')],
                  'domain': [('id', 'in', snapshots.ids)]}
        if len(snapshots) == 1:
            action.update(res_id=snapshots.id, view_mode='form', views=[(False, 'form')])
            return action
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': 'Carga de Sage completada', 'message': message,
                           'type': 'success', 'sticky': True, 'next': action}}

    def _parse_rows(self, rows):
        """Los totales de artículo son cabeceras; sus lotes son el detalle."""
        self.ensure_one()
        headers = None
        self.parse_warnings = False
        article = warehouse = article_name = ''
        price = 0
        group = None
        result = []
        block_rows = []
        block_values = []
        seen_blocks = set()
        seen_serials = set()
        quantities = {}
        model_cache = {}
        prefixes = sorted(self.env['product.category'].search([('parent_id', '=', False)]).mapped('name'), key=len, reverse=True)

        def number(value):
            if isinstance(value, str):
                value = value.strip().replace(' ', '')
                if ',' in value:
                    value = value.replace('.', '').replace(',', '.')
            return float(value or 0)

        def flush():
            if not group:
                return
            if group['article'] not in model_cache:
                model_cache[group['article']] = article_parts(self.env, group['article'], prefixes)
            model, state = model_cache[group['article']]
            base = {'session_id': self.session_id.id, 'warehouse_code': group['warehouse'],
                    'article_code': group['article'], 'article_name': group.get('name') or False,
                    'model_code': model,
                    'state_hint': state, 'cost': group['price']}
            real = [(s, q) for s, q in group['lots'] if s.upper().replace(' ', '') not in ('S/N', 'SN')]
            generic_qty = sum(q for s, q in group['lots'] if s.upper().replace(' ', '') in ('S/N', 'SN'))
            for serial, qty in real:
                block_values.append(dict(base, serial=serial, quantity=qty))
            remainder = group['quantity'] - sum(q for _s, q in real)
            if group['quantity'] >= 0:
                remainder = max(0, remainder)
            quantity = max(generic_qty, remainder) if group['quantity'] >= 0 else remainder
            if quantity:
                block_values.append(dict(base, quantity=quantity))

        def flush_block():
            if not block_rows:
                return
            fingerprint = hashlib.sha256(repr(block_rows).encode('utf-8')).digest()
            if fingerprint not in seen_blocks:
                seen_blocks.add(fingerprint)
                for val in block_values:
                    serial = normalize_serial(val.get('serial'))
                    key = (val['warehouse_code'], normalize_code(val['article_code']), serial)
                    if serial:
                        if key in seen_serials:
                            continue
                        seen_serials.add(key)
                    else:
                        if key in quantities:
                            previous = quantities[key]
                            total = previous['quantity'] + val['quantity']
                            if total:
                                previous['cost'] = (previous['cost'] * previous['quantity'] + val['cost'] * val['quantity']) / total
                            previous['quantity'] = total
                            continue
                        quantities[key] = val
                    result.append(val)
            block_rows.clear()
            block_values.clear()

        for row in rows:
            if headers is None:
                labels = [str(value or '').strip() for value in row]
                if all(label in labels for label in ('Almacén', 'Artículo', 'Lotes', 'Unidades')):
                    headers = {label: labels.index(label) for label in labels if label}
                    if 'Precio' not in headers:
                        self.parse_warnings = 'Falta la columna opcional Precio; se ha cargado sin costes.'
                continue
            def cell(label):
                index = headers.get(label)
                return row[index] if index is not None and index < len(row) else None
            def text(label):
                value = cell(label)
                return str(int(value)) if isinstance(value, float) and value.is_integer() else str(value or '').strip()
            wh, art, serial = text('Almacén'), text('Artículo'), text('Lotes')
            qty = cell('Unidades')
            if art:
                flush()
                group = None
                flush_block()
            block_rows.append(tuple(row))
            if art or wh:
                flush()
                group = None
                if art:
                    article = art
                    article_name = text('Nombre artículo')
                    price = number(cell('Precio'))
                if wh:
                    warehouse = wh
                if article and warehouse and warehouse != '000' and qty not in (None, '') and number(qty):
                    group = {'article': article, 'name': article_name, 'warehouse': warehouse, 'quantity': number(qty),
                             'price': number(cell('Precio') if cell('Precio') is not None else price), 'lots': []}
            if serial and group:
                group['lots'].append((serial, number(qty if qty is not None else 1)))
        flush()
        flush_block()
        if headers is None:
            raise UserError('No se encontró la cabecera de Valoración de stocks de Sage.')
        return result
