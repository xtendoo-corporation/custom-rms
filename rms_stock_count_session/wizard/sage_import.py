# -*- coding: utf-8 -*-
import base64
import binascii
import csv
import hashlib
from io import BytesIO
from zipfile import BadZipFile

from odoo import fields, models
from odoo.exceptions import AccessError, UserError

from ..models.sage_library import SAGE_COMPANIES, article_parts


class StockCountSageImport(models.TransientModel):
    _name = 'rms.stock.count.sage.import'
    _description = 'Cargar exportación de Sage'

    session_id = fields.Many2one('rms.stock.count.session', ondelete='cascade')
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    sage_company_code = fields.Selection(SAGE_COMPANIES, required=True, default='01')
    brand_categ_id = fields.Many2one('product.category', required=True, domain="[('parent_id', '=', False)]")
    mode = fields.Selection([('add', 'Añadir archivos'), ('replace', 'Reemplazar versión')], required=True, default='add')
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
        try:
            raw = base64.b64decode(self.file_data, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise UserError('El archivo no es válido.') from exc
        digest = hashlib.sha256(raw).hexdigest()
        Snapshot = self.env['rms.sage.snapshot']
        if not self.allow_duplicate and Snapshot.search_count([('file_hash', '=', digest), ('company_id', '=', self.company_id.id), ('sage_company_code', '=', self.sage_company_code), ('brand_categ_id', '=', self.brand_categ_id.id)]):
            raise UserError('Este archivo ya se cargó. Activa «Cargar aunque ya se haya cargado» para continuar.')
        workbook = None
        try:
            if (self.filename or '').lower().endswith('.csv') or not raw.startswith(b'PK'):
                try:
                    content = raw.decode('utf-8-sig')
                except UnicodeDecodeError:
                    content = raw.decode('latin-1')
                try:
                    dialect = csv.Sniffer().sniff(content[:8192], delimiters=';,')
                    rows = csv.reader(content.splitlines(), dialect)
                except csv.Error:
                    rows = csv.reader(content.splitlines(), delimiter=';')
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
        snapshot = Snapshot.create({'name': self.filename or 'Exportación Sage', 'company_id': self.company_id.id,
            'sage_company_code': self.sage_company_code, 'brand_categ_id': self.brand_categ_id.id,
            'export_date': self.export_date, 'filename': self.filename, 'attachment': self.file_data, 'file_hash': digest})
        for val in vals:
            val.pop('session_id', None)
            hint = val.pop('state_hint', 'Nuevo')
            val.update(snapshot_id=snapshot.id, state={'Nuevo': 'nuevo', 'Demo': 'demo', '2Mano': '2mano'}.get(hint, 'nuevo'))
        Line = self.env['rms.sage.stock.line'].sudo().with_context(tracking_disable=True, mail_notrack=True)
        for start in range(0, len(vals), 2000):
            Line.create(vals[start:start + 2000])
        snapshot.action_activate(self.mode)
        if self.parse_warnings:
            snapshot.quality_warnings = '\n'.join(filter(None, [snapshot.quality_warnings, self.parse_warnings]))
        return {'type': 'ir.actions.act_window', 'res_model': 'rms.sage.snapshot', 'res_id': snapshot.id, 'view_mode': 'form'}

    def _parse_rows(self, rows):
        """Los totales de artículo son cabeceras; sus lotes son el detalle."""
        self.ensure_one()
        headers = None
        self.parse_warnings = False
        article = warehouse = ''
        price = 0
        group = None
        result = []
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
            model, state = article_parts(self.env, group['article'], prefixes)
            base = {'session_id': self.session_id.id, 'warehouse_code': group['warehouse'],
                    'article_code': group['article'], 'model_code': model,
                    'state_hint': state, 'cost': group['price']}
            real = [(s, q) for s, q in group['lots'] if s.upper().replace(' ', '') not in ('S/N', 'SN')]
            generic_qty = sum(q for s, q in group['lots'] if s.upper().replace(' ', '') in ('S/N', 'SN'))
            for serial, qty in real:
                result.append(dict(base, serial=serial, quantity=qty))
            remainder = group['quantity'] - sum(q for _s, q in real)
            if group['quantity'] >= 0:
                remainder = max(0, remainder)
            quantity = max(generic_qty, remainder) if group['quantity'] >= 0 else remainder
            if quantity:
                result.append(dict(base, quantity=quantity))

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
            if art or wh:
                flush()
                group = None
                if art:
                    article = art
                    price = number(cell('Precio'))
                if wh:
                    warehouse = wh
                if article and warehouse and qty is not None:
                    group = {'article': article, 'warehouse': warehouse, 'quantity': number(qty),
                             'price': number(cell('Precio') if cell('Precio') is not None else price), 'lots': []}
            if serial and group:
                group['lots'].append((serial, number(qty if qty is not None else 1)))
        flush()
        if headers is None:
            raise UserError('No se encontró la cabecera de Valoración de stocks de Sage.')
        return result
