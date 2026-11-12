# -*- coding: utf-8 -*-
"""Cargar el maestro de artículos de Sage (Archivos > Artículos > Exportar)."""
import base64
import binascii
import csv
from io import BytesIO, StringIO
from zipfile import BadZipFile

from odoo import fields, models
from odoo.exceptions import AccessError, UserError

COLUMNS = {
    'Código': 'code', 'Nombre': 'name', 'Marca': 'brand_code', 'Nombre marca': 'brand_name',
    'Familia': 'family_code', 'Nombre familia': 'family_name', 'Subfamilia': 'subfamily_code',
    'Nombre subfamilia': 'subfamily_name', 'Baja': 'discontinued', 'Fecha baja': 'discontinued_date',
}


class SageArticleImport(models.TransientModel):
    _name = 'rms.sage.article.import'
    _description = 'Cargar maestro de artículos de Sage'

    file_data = fields.Binary(string='Maestro de artículos (Excel o CSV)', required=True)
    filename = fields.Char()

    def _rows(self, raw):
        if (self.filename or '').lower().endswith('.csv') or not raw.startswith(b'PK'):
            try:
                content = raw.decode('utf-8-sig')
            except UnicodeDecodeError:
                content = raw.decode('latin-1')
            return list(csv.reader(StringIO(content, newline=''), delimiter=';'))
        from openpyxl import load_workbook
        workbook = load_workbook(BytesIO(raw), read_only=True, data_only=True)
        try:
            return [list(row) for row in workbook.worksheets[0].iter_rows(values_only=True)]
        finally:
            workbook.close()

    def action_import(self):
        self.ensure_one()
        if not self.env.user.has_group('stock.group_stock_manager'):
            raise AccessError('Solo administración de inventario puede cargar Sage.')
        try:
            raw = base64.b64decode(self.file_data, validate=True)
            rows = self._rows(raw)
        except (ValueError, TypeError, OSError, binascii.Error, BadZipFile) as exc:
            raise UserError('No se puede leer el maestro de artículos: %s' % exc) from exc
        text = lambda value: (str(int(value)) if isinstance(value, float) and value.is_integer()
                              else str(value if value is not None else '').strip())
        header_index = next((i for i, row in enumerate(rows[:15])
                             if 'Código' in [text(c) for c in row] and 'Nombre marca' in [text(c) for c in row]), None)
        if header_index is None:
            raise UserError("No encuentro la cabecera del maestro (columnas 'Código' y 'Nombre marca').")
        header = [text(c) for c in rows[header_index]]
        index = {COLUMNS[h]: i for i, h in enumerate(header) if h in COLUMNS}
        Article = self.env['rms.sage.article'].sudo()
        existing = {a.code: a for a in Article.search([])}
        created = updated = 0
        to_create = []
        for row in rows[header_index + 1:]:
            vals = {field: text(row[i]) if i < len(row) else '' for field, i in index.items()}
            if not vals.get('code'):
                continue
            vals['discontinued'] = vals.get('discontinued', '').lower() in ('true', 'sí', 'si', '1', 'verdadero', 'x')
            key = vals['code'] = vals['code'].strip()
            article = existing.get(key)
            if article is True:
                continue  # repetido dentro del mismo archivo
            if article:
                changes = {k: v for k, v in vals.items() if article[k] != v}
                if changes:
                    article.write(changes)
                    updated += 1
            else:
                to_create.append(vals)
                existing[key] = True
        if to_create:
            Article.create(to_create)
            created = len(to_create)
        # Asignar la marca de Odoo a todos los artículos (crea las marcas que falten).
        Article._brands_by_article(Article.search([('brand_categ_id', '=', False)]).mapped('code'))
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': 'Maestro de artículos de Sage', 'type': 'success', 'sticky': True,
                           'message': 'Nuevos: %d · Actualizados: %d · Total en el maestro: %d' % (
                               created, updated, Article.search_count([])),
                           'next': {'type': 'ir.actions.act_window_close'}}}
