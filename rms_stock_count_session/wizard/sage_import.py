# -*- coding: utf-8 -*-
import base64
import binascii
from io import BytesIO
from zipfile import BadZipFile

from odoo import fields, models
from odoo.exceptions import UserError

from ..models.sage_expected import sage_article_parts


class StockCountSageImport(models.TransientModel):
    _name = 'rms.stock.count.sage.import'
    _description = 'Cargar exportación de Sage'

    session_id = fields.Many2one('rms.stock.count.session', required=True, ondelete='cascade')
    file_data = fields.Binary(string='Excel Valoración de stocks', required=True)
    filename = fields.Char(string='Nombre de archivo')

    def action_import(self):
        self.ensure_one()
        session = self.session_id
        session.check_access('write')
        if session.state in ('done', 'cancel'):
            raise UserError('El recuento está cerrado.')
        from openpyxl import load_workbook
        from openpyxl.utils.exceptions import InvalidFileException
        try:
            workbook = load_workbook(BytesIO(base64.b64decode(self.file_data)),
                                     read_only=True, data_only=True)
        except (ValueError, binascii.Error, OSError, KeyError, BadZipFile, InvalidFileException) as exc:
            raise UserError('No se puede leer el Excel de Sage: %s' % exc) from exc
        try:
            vals = self._parse_rows(workbook.active.iter_rows(values_only=True))
        except (ValueError, TypeError) as exc:
            raise UserError('El Excel de Sage contiene una cantidad o precio no válido: %s' % exc) from exc
        finally:
            workbook.close()
        session.expected_ids.unlink()
        self.env['rms.stock.count.expected'].create(vals)
        session.sage_line_ids.unlink()
        return {'type': 'ir.actions.act_window_close'}

    def _parse_rows(self, rows):
        """Los totales de artículo son cabeceras; sus lotes son el detalle."""
        self.ensure_one()
        headers = None
        article = warehouse = ''
        price = 0
        group = None
        result = []

        def flush():
            if not group:
                return
            model, state = sage_article_parts(group['article'])
            base = {'session_id': self.session_id.id, 'warehouse_code': group['warehouse'],
                    'article_code': group['article'], 'model_code': model,
                    'state_hint': state, 'cost': group['price']}
            real = [(s, q) for s, q in group['lots'] if s.upper().replace(' ', '') not in ('S/N', 'SN')]
            generic_qty = sum(q for s, q in group['lots'] if s.upper().replace(' ', '') in ('S/N', 'SN'))
            for serial, qty in real:
                result.append(dict(base, serial=serial, quantity=qty))
            remainder = max(0, group['quantity'] - sum(q for _s, q in real))
            quantity = max(generic_qty, remainder)
            if quantity:
                result.append(dict(base, quantity=quantity))

        for row in rows:
            if headers is None:
                labels = [str(value or '').strip() for value in row]
                if all(label in labels for label in ('Almacén', 'Artículo', 'Lotes', 'Unidades', 'Precio')):
                    headers = {label: labels.index(label) for label in labels if label}
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
                    price = float(cell('Precio') or 0)
                if wh:
                    warehouse = wh
                if article and warehouse and qty is not None:
                    group = {'article': article, 'warehouse': warehouse, 'quantity': float(qty or 0),
                             'price': float(cell('Precio') if cell('Precio') is not None else price), 'lots': []}
            if serial and group:
                group['lots'].append((serial, float(qty if qty is not None else 1)))
        flush()
        if headers is None:
            raise UserError('No se encontró la cabecera de Valoración de stocks de Sage.')
        return result
