# -*- coding: utf-8 -*-
"""Cargar costes desde Excel: columnas artículo o referencia, estado
(opcional) y coste. Solo rellena el coste de las líneas de la carga."""
import base64
import io
import re
import unicodedata
from collections import defaultdict

from odoo import fields, models
from odoo.exceptions import UserError

from odoo.addons.rms_stock_count_session.models.scan_rule import normalize_code

STATE_WORDS = {
    'NUEVO': 'new', 'NEW': 'new', 'N': 'new',
    'DEMO': 'demo', 'D': 'demo',
    'EXDEMO': 'ex_demo', 'EX': 'ex_demo',
    '2MANO': 'second_hand', '2AMANO': 'second_hand', 'SEGUNDAMANO': 'second_hand', '2M': 'second_hand',
    'SECONDHAND': 'second_hand',
}


def _plain(text):
    text = unicodedata.normalize('NFKD', str(text or ''))
    text = ''.join(char for char in text if not unicodedata.combining(char))
    return re.sub(r'[^A-Z0-9]', '', text.upper())


def _number(value):
    if value in (None, ''):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace('€', '').replace(' ', '')
    if ',' in text:
        text = text.replace('.', '').replace(',', '.')
    try:
        return float(text)
    except ValueError:
        return None


class InitialLoadCostImport(models.TransientModel):
    _name = 'rms.initial.load.cost.import'
    _description = 'Cargar costes de la carga de arranque desde Excel'

    load_id = fields.Many2one('rms.initial.load', string='Carga', required=True, ondelete='cascade')
    file = fields.Binary(string='Excel de costes', attachment=False)
    filename = fields.Char()
    overwrite = fields.Boolean(string='Sustituir los costes ya puestos', default=True)
    result = fields.Text(string='Resultado', readonly=True)

    def _read_rows(self):
        from openpyxl import load_workbook
        try:
            book = load_workbook(io.BytesIO(base64.b64decode(self.file)), read_only=True, data_only=True)
        except Exception as error:  # noqa: BLE001
            raise UserError('No se puede leer el archivo. Tiene que ser un Excel (.xlsx).') from error
        rows = list(book.active.iter_rows(values_only=True))
        header_index, columns = None, {}
        for index, row in enumerate(rows[:15]):
            names = [_plain(cell) for cell in row]
            found = {}
            for position, name in enumerate(names):
                if not name:
                    continue
                if 'ref' not in found and (name.startswith('ART') or name.startswith('REF') or name.startswith('COD')):
                    found['ref'] = position
                elif 'state' not in found and name.startswith('ESTADO'):
                    found['state'] = position
                elif 'cost' not in found and (name.startswith('COST') or name.startswith('PRECIO') or name.startswith('IMPORTE')):
                    found['cost'] = position
            if 'ref' in found and 'cost' in found:
                header_index, columns = index, found
                break
        if header_index is None:
            raise UserError('No encuentro las columnas. La primera fila debe tener «Artículo» (o «Referencia»), '
                            '«Estado» (opcional) y «Coste».')
        result = []
        for row in rows[header_index + 1:]:
            if not row or len(row) <= max(columns.values()):
                continue
            reference = row[columns['ref']]
            cost = _number(row[columns['cost']])
            if reference in (None, '') or cost is None:
                continue
            state = row[columns['state']] if 'state' in columns else None
            result.append((str(reference).strip(), _plain(state), cost))
        return result

    def action_import(self):
        self.ensure_one()
        load = self.load_id
        load._check_manager()
        if load.state != 'prepared':
            raise UserError('Los costes se cargan con la carga preparada y antes de aplicarla.')
        if not self.file:
            raise UserError('Elige el Excel de costes.')
        rows = self._read_rows()
        Line = self.env['rms.initial.load.line'].sudo()
        lines = Line.search([('load_id', '=', load.id), ('kind', '!=', 'skip')])
        # Cada línea se puede encontrar por la referencia del producto, su
        # código de barras o el artículo de Sage (con o sin D- / 2M-).
        index = defaultdict(lambda: Line.browse())
        for line in lines:
            keys = {normalize_code(line.product_id.default_code or ''), normalize_code(line.product_id.barcode or ''),
                    normalize_code(line.article_code or '')}
            for key in keys - {''}:
                index[key] |= line
        updated = Line.browse()
        unknown, bad_state = [], []
        # Primero las filas sin estado (valen para todos) y luego las que lo concretan.
        for reference, state_word, cost in sorted(rows, key=lambda row: bool(row[1])):
            found = index.get(normalize_code(reference))
            if not found:
                unknown.append(reference)
                continue
            if state_word:
                code = STATE_WORDS.get(state_word)
                if not code:
                    bad_state.append('%s (%s)' % (reference, state_word))
                    continue
                found = found.filtered(lambda l: l.state_id.code == code)
            if not self.overwrite:
                found = found.filtered(lambda l: not l.cost) | (found & updated)
            if found:
                found.write({'cost': cost})
                updated |= found
        load.sudo()._refresh_summary()
        message = ['Filas leídas: %d. Líneas de la carga con coste puesto: %d.' % (len(rows), len(updated))]
        if unknown:
            message.append('No están en la carga (%d): %s' % (len(unknown), ', '.join(unknown[:30])))
        if bad_state:
            message.append('Estado no reconocido (%d): %s' % (len(bad_state), ', '.join(bad_state[:30])))
        message.append('Unidades que siguen sin coste: %s' % load.no_cost_units)
        self.result = '\n'.join(message)
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id,
                'view_mode': 'form', 'target': 'new'}
