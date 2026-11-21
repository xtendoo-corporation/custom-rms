# -*- coding: utf-8 -*-
"""Excel de la carga: una hoja de resumen y una hoja por tipo de línea."""
import base64
import io

from odoo import fields, models

from .initial_load import KIND_HELP, KINDS, NO_PARTNER, SITE_NAMES, _fmt

SAGE_STATE = {'nuevo': 'Nuevo', 'demo': 'Demo', '2mano': '2ª Mano'}
RESULT = {'pending': 'Sin aplicar', 'done': 'Cargado', 'duplicate': 'Ya tenía existencias: no duplicado',
          'undone': 'Deshecho', 'not_undone': 'No se pudo deshacer'}
SHEET_TITLES = {
    'counted': 'Contado', 'sage_unverified': 'Según Sage sin verificar', 'alta': 'Altas',
    'phantom': 'Pendiente de localizar', 'deposit': 'Depósitos heredados', 'qty_counted': 'Cantidad contada',
    'qty_sage': 'Cantidad Sage sin verificar', 'skip': 'No cargado',
}
HEAD = ['Nave', 'Empresa', 'Entra en', 'Referencia', 'Producto', 'Artículo Sage', 'Nº de serie', 'Estado final',
        'Estado en Sage', 'Cantidad', 'Cantidad en Sage', 'Contado en la nave', 'Coste unitario', 'Coste en Sage',
        'No verificado', 'Cliente del depósito', 'Cliente según Sage', 'Fecha del depósito', 'Depósito a cerrar en Sage',
        'Movimiento de Sage aplicado', 'Recuento', 'Leído el', 'Almacén Sage', 'Resultado', 'Motivo',
        'Por qué no se pudo deshacer']


class InitialLoad(models.Model):
    _inherit = 'rms.initial.load'

    def _export_row(self, line):
        move = line.sage_move_id
        return [
            line.site_name, line.company_id.name, line.destination, line.product_id.default_code,
            line.product_id.name, line.article_code, line.lot_name, line.state_id.name,
            SAGE_STATE.get(line.sage_state), line.quantity, line.sage_qty or None, line.counted_qty or None,
            line.cost or None, line.sage_cost or None, 'Sí' if line.unverified else '',
            line.partner_id.name if line.kind == 'deposit' else '', line.sage_partner_name,
            line.deposit_date, 'Sí' if line.deposit_to_close else '',
            move._label() if move else '', line.session_id.name, line.scanned_at, line.sage_warehouse_code,
            RESULT.get(line.apply_result), line.note, line.undo_note,
        ]

    def _cell(self, value):
        if value is False or value is None:
            return ''
        if hasattr(value, 'tzinfo'):
            return fields.Datetime.context_timestamp(self, value).replace(tzinfo=None)
        return value

    def _export_workbook(self):
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter

        self.ensure_one()
        load = self.sudo()
        Line = self.env['rms.initial.load.line'].sudo()
        bold = Font(bold=True)
        fill = PatternFill('solid', fgColor='D9E1F2')
        book = Workbook()
        cover = book.active
        cover.title = 'Resumen'
        table, totals, counts = load._summary_data()
        cover.append(['Carga de arranque: %s' % load.name])
        cover['A1'].font = Font(bold=True, size=14)
        cover.append(['Fecha', load.date])
        cover.append(['Situación', dict(self._fields['state'].selection).get(load.state)])
        cover.append(['Naves contadas', load.counted_sites_label])
        cover.append([])
        for label, value in load._extra_figures():
            cover.append([label, value])
        cover.append([])
        start = cover.max_row + 1
        cover.append(['Nave', 'Empresa'] + [label for _kind, label in KINDS])
        for cell in cover[start]:
            cell.font, cell.fill = bold, fill
        for (site, company), kinds in sorted(table.items(), key=lambda item: (item[0][0] or 99, item[0][1].id or 0)):
            cover.append([SITE_NAMES.get(site, 'Sin nave'), company.name or '—'] +
                         [kinds.get(kind) or None for kind, _label in KINDS])
        cover.append(['Total (unidades)', ''] + [totals.get(kind) or 0 for kind, _label in KINDS])
        for cell in cover[cover.max_row]:
            cell.font = bold
        cover.append([])
        cover.append(['Hoja', 'Líneas', 'Qué es'])
        for cell in cover[cover.max_row]:
            cell.font, cell.fill = bold, fill
        extra_sheets = [
            ('Depósitos a cerrar en Sage', [('deposit_to_close', '=', True)],
             'Sage los tiene en depósito en un cliente pero se han leído en la nave: entran en la nave. '
             'Hay que cerrar el depósito en Sage.'),
            ('Clientes sin casar', [('kind', '=', 'deposit'), ('partner_id', '=', self.env.ref(
                'rms_stock_initial_load.partner_inherited_deposits').id)],
             'Depósitos cuyo cliente de Sage no coincide con un único contacto de Odoo: quedan con el contacto '
             'genérico y el nombre de Sage. Asignar el cliente en el depósito.'),
            ('Depósitos sin cliente', [('kind', '=', 'deposit'), ('sage_partner_name', '=', NO_PARTNER)],
             'Depósitos heredados sin cliente identificado: ni la línea de depósito de Sage ni sus movimientos '
             'dicen en qué cliente está el equipo. Quedan con el contacto genérico: averiguar el cliente.'),
            ('Movimientos posteriores', [('sage_move_id', '!=', False)],
             'Líneas en las que se ha aplicado un movimiento de Sage posterior al recuento.'),
            ('Estados revisados', [('review_id', '!=', False)],
             'Equipos cuyo estado leído no coincidía con Sage y se ha revisado uno a uno.'),
            ('Ya estaban en Odoo', [('apply_result', '=', 'duplicate')],
             'Nº de serie que ya tenían existencias en Odoo al aplicar: no se han duplicado.'),
            ('No se pudo deshacer', [('undo_note', '!=', False)],
             'Líneas que «Deshacer carga» no ha podido revertir porque lo cargado ya se había movido, vendido '
             'o reservado. El motivo de cada una está en la última columna.'),
        ]
        sheets = [(SHEET_TITLES[kind], [('kind', '=', kind)], KIND_HELP[kind]) for kind, _label in KINDS] + extra_sheets
        for title, domain, description in sheets:
            lines = Line.search([('load_id', '=', load.id)] + domain)
            cover.append([title, len(lines), description])
            sheet = book.create_sheet(title[:31])
            sheet.append(HEAD)
            for cell in sheet[1]:
                cell.font, cell.fill = bold, fill
            rows = []
            for start_index in range(0, len(lines), 1000):
                chunk = lines[start_index:start_index + 1000]
                for line in chunk:
                    row = [self._cell(value) for value in self._export_row(line)]
                    rows.append(row)
                    sheet.append(row)
            sheet.freeze_panes = 'A2'
            if rows:
                sheet.auto_filter.ref = sheet.dimensions
            for index, column in enumerate(HEAD, start=1):
                width = max([len(str(column))] + [len(str(r[index - 1] or '')) for r in rows[:300]])
                sheet.column_dimensions[get_column_letter(index)].width = min(max(width + 2, 10), 70)
        cover.column_dimensions['A'].width = 52
        cover.column_dimensions['B'].width = 26
        for letter in 'CDEFGHIJ':
            cover.column_dimensions[letter].width = 24
        for row in cover.iter_rows(min_row=start):
            for cell in row:
                cell.alignment = Alignment(wrap_text=True, vertical='top')
        stream = io.BytesIO()
        book.save(stream)
        return stream.getvalue()

    def action_export_excel(self):
        self.ensure_one()
        self._check_manager()
        if self.state == 'draft':
            from odoo.exceptions import UserError
            raise UserError('Pulsa antes «Preparar»: todavía no hay nada que exportar.')
        content = self._export_workbook()
        now = fields.Datetime.context_timestamp(self, fields.Datetime.now())
        attachment = self.env['ir.attachment'].sudo().create({
            'name': 'Carga_de_arranque_%s_%s.xlsx' % (self.id, now.strftime('%Y-%m-%d_%H%M')),
            'datas': base64.b64encode(content), 'res_model': self._name, 'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })
        return {'type': 'ir.actions.act_url', 'url': '/web/content/%d?download=true' % attachment.id,
                'target': 'self'}


_ = _fmt
