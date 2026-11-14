# -*- coding: utf-8 -*-
"""Sage en vivo: el extractor del NAS lee Sage (solo lectura) y lo envía aquí
por la API JSON-2. Sustituye a subir a mano las exportaciones de "Valoración
de stocks" y "Depósitos de venta", y guarda los movimientos de Sage por número
de serie para saber si un equipo se movió después de contarlo.

API (todo con @api.model, solo administración de inventario):
- rms.sage.sync.run/push_stock(sage_company_code, stock_kind, rows, export_date)
- rms.sage.sync.run/push_moves(rows)
- rms.sage.sync.run/last_watermark()
"""
import base64
import hashlib
import json
import time

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

from .sage_expected import normalize_serial
from .sage_library import SAGE_COMPANIES, STOCK_KINDS
from .scan_rule import normalize_code

MOVE_TYPES = [
    ('sale', 'Venta'),
    ('deposit', 'Depósito a cliente'),
    ('deposit_return', 'Vuelta de depósito'),
    ('transfer', 'Traspaso'),
    ('purchase', 'Compra'),
    ('adjustment', 'Regularización'),
    ('initial', 'Stock inicial'),
]
MOVE_LABELS = dict(MOVE_TYPES)
SHORT_LABELS = {'sale': 'venta', 'deposit': 'depósito', 'deposit_return': 'vuelta de depósito',
                'transfer': 'traspaso', 'purchase': 'compra', 'adjustment': 'regularización',
                'initial': 'stock inicial'}
# Filas por llamada que acepta push_moves (el extractor parte en tandas).
MAX_MOVES_PER_CALL = 5000
MAX_STOCK_ROWS = 60000


class SageSerialMove(models.Model):
    _name = 'rms.sage.serial.move'
    _description = 'Movimiento de Sage por número de serie'
    _order = 'move_date desc, id desc'
    _rec_name = 'serial'

    sage_key = fields.Char(string='Clave Sage', required=True, index=True,
                           help='Identificador único de la línea en Sage (GUID o empresa+tabla+documento+línea+serie).')
    sage_table = fields.Char(string='Tabla Sage', index=True)
    sage_modified = fields.Datetime(string='Modificado en Sage', index=True)
    sage_company_code = fields.Selection(SAGE_COMPANIES, string='Empresa Sage', index=True)
    move_type = fields.Selection(MOVE_TYPES, string='Tipo', required=True, index=True)
    move_date = fields.Date(string='Fecha', index=True)
    article_code = fields.Char(string='Artículo Sage', index=True)
    serial = fields.Char(string='Nº de serie')
    serial_normalized = fields.Char(compute='_compute_serial_normalized', store=True, index=True)
    quantity = fields.Float(string='Unidades')
    warehouse_from = fields.Char(string='Almacén origen')
    warehouse_to = fields.Char(string='Almacén destino')
    document = fields.Char(string='Documento')
    partner_name = fields.Char(string='Cliente / proveedor')
    product_id = fields.Many2one('product.product', string='Producto', index=True)

    _sage_key_unique = models.Constraint('UNIQUE(sage_key)', 'Ese movimiento de Sage ya está cargado.')

    @api.depends('serial')
    def _compute_serial_normalized(self):
        for move in self:
            move.serial_normalized = normalize_serial(move.serial)

    def _label(self):
        """'depósito a ACME (14-nov)' para el escáner y el checklist."""
        self.ensure_one()
        text = SHORT_LABELS.get(self.move_type, self.move_type or '')
        if self.partner_name and self.move_type in ('sale', 'deposit', 'deposit_return'):
            text += (' de ' if self.move_type == 'deposit_return' else ' a ') + self.partner_name.strip()
        if self.move_type == 'transfer' and (self.warehouse_from or self.warehouse_to):
            text += ' %s → %s' % (self.warehouse_from or '?', self.warehouse_to or '?')
        if self.move_date:
            text += ' (%s)' % self.move_date.strftime('%d-%m-%Y')
        return text

    @api.model
    def _latest_after(self, pairs):
        """{(serial_normalized, fecha): movimiento más reciente de esa serie con
        fecha >= fecha}. pairs = [(serial_normalized, date)]."""
        keys = {serial for serial, _date in pairs if serial}
        if not keys:
            return {}
        moves = self.search([('serial_normalized', 'in', list(keys))], order='move_date desc, id desc')
        by_serial = {}
        for move in moves:
            by_serial.setdefault(move.serial_normalized, self.browse())
            by_serial[move.serial_normalized] |= move
        result = {}
        for serial, date in pairs:
            for move in by_serial.get(serial, []):
                if move.move_date and date and move.move_date >= date:
                    result[(serial, date)] = move
                    break
        return result


class SageSyncRun(models.Model):
    _name = 'rms.sage.sync.run'
    _description = 'Sincronización Sage en vivo'
    _order = 'id desc'

    name = fields.Char(string='Qué', required=True)
    kind = fields.Selection([('stock', 'Existencias'), ('deposit', 'Depósitos'), ('moves', 'Movimientos')],
                            string='Tipo', required=True)
    sage_company_code = fields.Selection(SAGE_COMPANIES, string='Empresa Sage')
    rows = fields.Integer(string='Filas recibidas')
    created = fields.Integer(string='Nuevas')
    updated = fields.Integer(string='Actualizadas')
    state = fields.Selection([('ok', 'Correcta'), ('nochange', 'Sin cambios'), ('error', 'Error')],
                             string='Resultado', default='ok', required=True)
    message = fields.Text(string='Detalle')
    duration = fields.Float(string='Segundos', digits=(10, 2))

    @api.model
    def _check_api_access(self):
        if not self.env.user.has_group('stock.group_stock_manager'):
            raise AccessError('Solo administración de inventario puede enviar datos de Sage.')

    # ------------------------------------------------------------------ stock
    @api.model
    def push_stock(self, sage_company_code, stock_kind, rows, export_date=None):
        """Sustituye la versión vigente de Sage de esa empresa y tipo por estas
        filas: [{warehouse_code, article_code, article_name, serial, quantity,
        cost, partner_name}]. Lo contado no se toca. Si el contenido es igual al
        vigente no hace nada (llamada idempotente)."""
        started = time.time()
        self._check_api_access()
        if sage_company_code not in dict(SAGE_COMPANIES):
            raise UserError('Empresa Sage desconocida: %s' % sage_company_code)
        if stock_kind not in dict(STOCK_KINDS):
            raise UserError('Tipo desconocido: %s' % stock_kind)
        if not isinstance(rows, list) or len(rows) > MAX_STOCK_ROWS:
            raise UserError('Filas no válidas o demasiadas (máximo %s).' % MAX_STOCK_ROWS)
        canonical = json.dumps(sorted(
            [[r.get('warehouse_code') or '', r.get('article_code') or '', r.get('serial') or '',
              round(float(r.get('quantity') or 0), 4), r.get('partner_name') or ''] for r in rows]),
            separators=(',', ':')).encode()
        digest = hashlib.sha256(canonical).hexdigest()
        company = self._company_for(sage_company_code)
        Snapshot = self.env['rms.sage.snapshot'].sudo()
        same = Snapshot.search_count([('state', '=', 'current'), ('file_hash', '=', digest),
                                      ('sage_company_code', '=', sage_company_code), ('stock_kind', '=', stock_kind),
                                      ('company_id', '=', company.id)])
        name = 'Sage en vivo %s %s' % (sage_company_code, dict(STOCK_KINDS)[stock_kind].lower())
        if same:
            run = self.create({'name': name, 'kind': 'deposit' if stock_kind == 'deposit' else 'stock',
                               'sage_company_code': sage_company_code, 'rows': len(rows), 'state': 'nochange',
                               'duration': time.time() - started})
            return {'status': 'nochange', 'run_id': run.id}
        Wizard = self.env['rms.stock.count.sage.import'].sudo()
        wizard = Wizard.create({
            'company_id': company.id, 'sage_company_code': sage_company_code, 'scope': 'all', 'mode': 'replace',
            'stock_kind': stock_kind, 'export_date': export_date or fields.Date.context_today(self),
            'filename': '%s.json' % name, 'allow_duplicate': True,
            # Solo un resumen pequeño como "archivo" de la versión.
            'file_data': base64.b64encode(json.dumps(
                {'origen': 'sage_live', 'filas': len(rows), 'sha256': digest}).encode()),
        })
        vals = wizard._vals_from_api_rows(rows)
        if not vals:
            raise UserError('No llega ninguna existencia.')
        summary, _snapshots = wizard._load_values(vals, digest)
        run = self.create({'name': name, 'kind': 'deposit' if stock_kind == 'deposit' else 'stock',
                           'sage_company_code': sage_company_code, 'rows': len(rows), 'created': len(vals),
                           'state': 'ok', 'message': summary, 'duration': time.time() - started})
        return {'status': 'ok', 'run_id': run.id, 'lines': len(vals)}

    @api.model
    def _company_for(self, sage_company_code):
        """Empresa de Odoo de una empresa de Sage: la de la última versión
        cargada; si no hay, la empresa actual del usuario."""
        last = self.env['rms.sage.snapshot'].sudo().search(
            [('sage_company_code', '=', sage_company_code)], order='id desc', limit=1)
        return last.company_id or self.env.company

    # ------------------------------------------------------------ movimientos
    @api.model
    def push_moves(self, rows):
        """Crea o actualiza movimientos por su clave de Sage (idempotente):
        [{sage_key, sage_table, sage_modified, sage_company_code, move_type,
        move_date, article_code, serial, quantity, warehouse_from, warehouse_to,
        document, partner_name}]."""
        started = time.time()
        self._check_api_access()
        if not isinstance(rows, list) or len(rows) > MAX_MOVES_PER_CALL:
            raise UserError('Envía como máximo %s movimientos por llamada.' % MAX_MOVES_PER_CALL)
        Move = self.env['rms.sage.serial.move'].sudo()
        fields_allowed = set(Move._fields) - {'id', 'serial_normalized', 'product_id'}
        valid_types = dict(MOVE_TYPES)
        clean = {}
        for row in rows:
            key = (row.get('sage_key') or '').strip()
            if not key or row.get('move_type') not in valid_types:
                continue
            clean[key] = {k: v for k, v in row.items() if k in fields_allowed}
            clean[key]['sage_key'] = key
        existing = {m.sage_key: m for m in Move.search([('sage_key', 'in', list(clean))])}
        products = self._products_for_articles({v.get('article_code') for v in clean.values()})
        to_create, updated = [], 0
        for key, vals in clean.items():
            vals['product_id'] = products.get(normalize_code(vals.get('article_code') or ''), False)
            move = existing.get(key)
            if move:
                # Solo si Sage la ha modificado desde la última vez.
                new_modified = (vals.get('sage_modified') or '')[:19]
                if new_modified and fields.Datetime.to_string(move.sage_modified) != new_modified:
                    move.write({k: v for k, v in vals.items() if k != 'sage_key'})
                    updated += 1
            else:
                to_create.append(vals)
        for start in range(0, len(to_create), 2000):
            Move.create(to_create[start:start + 2000])
        run = self.create({'name': 'Movimientos de Sage', 'kind': 'moves', 'rows': len(rows),
                           'created': len(to_create), 'updated': updated,
                           'state': 'ok' if (to_create or updated) else 'nochange',
                           'duration': time.time() - started})
        return {'status': 'ok', 'run_id': run.id, 'created': len(to_create), 'updated': updated}

    @api.model
    def _products_for_articles(self, article_codes):
        """{artículo normalizado: producto} con lo ya resuelto en las existencias
        de Sage y el mapa de artículos (sin búsquedas caras)."""
        keys = [normalize_code(code) for code in article_codes if code]
        if not keys:
            return {}
        result = {}
        self.env['rms.sage.stock.line'].flush_model(['article_normalized', 'product_id'])
        self.env.cr.execute("""
            SELECT DISTINCT ON (article_normalized) article_normalized, product_id
              FROM rms_sage_stock_line
             WHERE article_normalized = ANY(%s) AND product_id IS NOT NULL
             ORDER BY article_normalized, id DESC""", (keys,))
        result.update(dict(self.env.cr.fetchall()))
        missing = [key for key in keys if key not in result]
        if missing:
            for mapping in self.env['rms.sage.article.map'].sudo().search([('article_code', 'in', missing)]):
                variant = mapping.product_tmpl_id.product_variant_id
                if variant:
                    result[mapping.article_code] = variant.id
        missing = [key for key in keys if key not in result]
        if missing:
            # Referencia interna igual que el artículo (sin prefijos de estado).
            stripped = {}
            for key in missing:
                for prefix in ('2M', 'DEMO', 'D'):
                    if key.startswith(prefix) and len(key) > len(prefix) + 2:
                        stripped.setdefault(key[len(prefix):], key)
                stripped.setdefault(key, key)
            products = self.env['product.product'].sudo().search(
                [('rms_default_code_normalized', 'in', list(stripped))])
            for product in products:
                original = stripped[product.rms_default_code_normalized]
                result.setdefault(original, product.id)
                result.setdefault(product.rms_default_code_normalized, product.id)
        return result

    @api.model
    def last_watermark(self):
        """{tabla de Sage: fecha 'MODIFIED' más reciente recibida} para que el
        extractor solo envíe lo nuevo."""
        self._check_api_access()
        self.env['rms.sage.serial.move'].flush_model(['sage_table', 'sage_modified'])
        self.env.cr.execute("""
            SELECT sage_table, max(sage_modified) FROM rms_sage_serial_move
             WHERE sage_table IS NOT NULL GROUP BY sage_table""")
        return {table: fields.Datetime.to_string(value) for table, value in self.env.cr.fetchall() if value}
