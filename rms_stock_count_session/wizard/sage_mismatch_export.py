# -*- coding: utf-8 -*-
"""Excel de descuadres: un solo archivo para Administración con una hoja por
tipo de diferencia entre lo contado y Sage. Solo lee; no cambia nada."""
import base64
import io
import re

from odoo import fields, models

from ..models.sage_library import SAGE_COMPANIES

SITES = [('1', 'Madrid'), ('2', 'Nave 22'), ('3', 'Alfaomega'), ('4', 'Cataluña (Alex)'),
         ('5', 'Cataluña (Vicente)'), ('6', 'Mallorca'), ('7', 'Sevilla')]
SAGE_STATE = {'nuevo': 'Nuevo', 'demo': 'Demo', '2mano': '2ª Mano'}
COMPANY = dict(SAGE_COMPANIES)
SHEETS = [
    ('missing', 'No leídos', 'Sage lo tiene en la nave y nadie lo ha leído. Buscarlo o darlo de baja en Sage.'),
    ('extra', 'Altas', 'Se ha leído y Sage no lo tiene. Darlo de alta o corregir el nº de serie en Sage.'),
    ('typo', 'Nº de serie mal escrito en Sage',
     'La etiqueta del equipo lleva un nº de serie y Sage otro muy parecido (un carácter de más, de menos o '
     'cambiado). Arriba, los que un operario ha confirmado: corregir el nº de serie en Sage. Abajo, «por '
     'confirmar»: sugerencias que nadie ha contestado todavía en el escáner.'),
    ('state', 'Estado distinto', 'El estado marcado al leer no es el de Sage. Cambiar el artículo en Sage (D-, 2M-).'),
    ('deposit', 'En depósito y en nave', 'Sage lo tiene en depósito en un cliente pero se ha leído en la nave. Cerrar el depósito.'),
    ('site', 'En otra nave', 'Se ha leído en una nave distinta de la que dice Sage. Hacer el traspaso en Sage.'),
    ('dup', 'Duplicados en Sage', 'El mismo nº de serie y modelo en dos almacenes de Sage.'),
    ('negative', 'Negativos en Sage', 'Nº de serie con cantidad negativa o cero en Sage.'),
    ('moved', 'Movidos tras contar', 'Sage lo ha movido después de leerlo. Es un movimiento real: no hay que hacer nada.'),
    ('multi', 'En varios recuentos', 'El mismo equipo leído en más de un recuento.'),
    ('qty', 'Por cantidad', 'Artículos sin nº de serie (cables, fundas, hierros): lo contado en la nave no coincide '
                            'con Sage (las tres empresas sumadas) o aún no se ha contado. Recontar o regularizar en Sage.'),
]


class SageMismatchExport(models.TransientModel):
    _name = 'rms.sage.mismatch.export'
    _description = 'Excel de descuadres con Sage'

    sage_company_code = fields.Selection(SAGE_COMPANIES, string='Empresa',
                                         help='Vacío: las tres empresas.')
    site_number = fields.Selection(SITES, string='Nave', help='Vacío: todas las naves.')
    file = fields.Binary(string='Archivo', readonly=True, attachment=False)
    filename = fields.Char(readonly=True)
    summary = fields.Text(string='Resumen', readonly=True)

    # ------------------------------------------------------------------
    def _base_domain(self):
        domain = []
        if self.sage_company_code:
            domain.append(('sage_company_code', '=', self.sage_company_code))
        if self.site_number:
            domain.append(('sage_warehouse_id.site_number', '=', int(self.site_number)))
        return domain

    @staticmethod
    def _location_site(location):
        digits = re.search(r'(\d+)$', (location.warehouse_id.code or '').strip())
        return int(digits.group(1)) if digits else 0

    def _warehouse_label(self, record):
        warehouse = record.sage_warehouse_id
        return '%s (%s)' % (warehouse.name, warehouse.code) if warehouse else (record.warehouse_code or '')

    def _checklist_row(self, row):
        return [COMPANY.get(row.sage_company_code, ''), self._warehouse_label(row), row.brand_categ_id.name or '',
                row.article_code or '', row.article_name or row.product_id.display_name or '',
                SAGE_STATE.get(row.sage_state, ''), row.serial or '']

    def _collect(self):
        """{clave: (cabecera, filas)} con todas las hojas."""
        self.ensure_one()
        Checklist = self.env['rms.sage.checklist'].sudo()
        base = self._base_domain()
        head = ['Empresa', 'Almacén Sage', 'Marca', 'Artículo Sage', 'Nombre', 'Estado en Sage', 'Nº de serie']
        data = {}

        rows = Checklist.search(base + [('pending_qty', '=', 1)])
        data['missing'] = (head, [self._checklist_row(r) for r in rows])

        rows = Checklist.search(base + [('counted', '=', True), ('state_mismatch', '=', True)])
        data['state'] = (head + ['Estado marcado al leer', 'Recuento', 'Leído el'],
                         [self._checklist_row(r) + [r.physical_state_id.name or '', r.first_session_id.name or '',
                                                    r.first_scanned_at] for r in rows])

        rows = Checklist.search(base + [('counted', '=', True), ('in_deposit', '=', True)])
        data['deposit'] = (head + ['Cliente del depósito', 'Recuento', 'Leído el'],
                           [self._checklist_row(r) + [r.deposit_partner or '', r.first_session_id.name or '',
                                                      r.first_scanned_at] for r in rows])

        # Leído en otra nave: no se filtra por la nave de Sage sino por la de la lectura.
        company_domain = [d for d in base if d[0] == 'sage_company_code']
        site_rows = []
        for r in Checklist.search(company_domain + [('counted', '=', True), ('in_deposit', '=', False)]):
            location = r.first_scan_id.location_id or r.first_session_id.location_id
            read_site = self._location_site(location)
            sage_site = r.sage_warehouse_id.site_number
            if not read_site or read_site == sage_site:
                continue
            if self.site_number and int(self.site_number) not in (read_site, sage_site):
                continue
            site_rows.append(self._checklist_row(r) + [location.complete_name or '', r.first_session_id.name or '',
                                                       r.first_scanned_at])
        data['site'] = (head + ['Leído en', 'Recuento', 'Leído el'], site_rows)

        rows = Checklist.search(base + [('moved_after_count', '=', True)])
        move_label = dict(Checklist._fields['moved_type'].selection)
        data['moved'] = (head + ['Movimiento', 'Fecha', 'Documento Sage', 'Cliente / proveedor'],
                         [self._checklist_row(r) + [move_label.get(r.moved_type, ''), r.moved_date,
                                                    r.moved_document or '', r.moved_partner or ''] for r in rows])

        rows = Checklist.search(base + [('multi_session', '=', True)])
        data['multi'] = (head + ['Nº de recuentos', 'Primer recuento'],
                         [self._checklist_row(r) + [r.session_count, r.first_session_id.name or ''] for r in rows])

        Line = self.env['rms.sage.stock.line'].sudo()
        line_domain = base + [('is_current', '=', True), ('stock_kind', '=', 'stock'), ('serial_normalized', '!=', '')]
        order = 'serial_normalized, sage_company_code, warehouse_code'
        data['dup'] = (head, [self._line_row(l) for l in Line.search(line_domain + [('dup_count', '>', 1)], order=order)])
        data['negative'] = (head + ['Cantidad'],
                            [self._line_row(l) + [l.quantity]
                             for l in Line.search(line_domain + [('quantity', '<=', 0)], order=order)])

        # Un alta no está en Sage en ninguna empresa: solo se filtra por nave.
        extra_domain = [('moved_after_count', '=', False)]
        extra_rows = []
        for r in self.env['rms.sage.checklist.extra'].sudo().search(extra_domain):
            site = self._location_site(r.location_id or r.session_id.location_id)
            if self.site_number and site != int(self.site_number):
                continue
            extra_rows.append([r.session_id.company_id.name or '', (r.location_id or r.session_id.location_id).complete_name or '',
                               r.product_id.categ_id.name or '', r.product_id.default_code or '',
                               r.product_id.name or 'Sin identificar', r.product_state_id.name or '',
                               r.lot_name or r.code or '', r.session_id.name or '', r.operator_id.display_name or '',
                               r.scanned_at])
        data['extra'] = (['Empresa del recuento', 'Leído en', 'Marca', 'Referencia', 'Producto', 'Estado marcado',
                          'Nº de serie', 'Recuento', 'Operario', 'Leído el'], extra_rows)
        data['qty'] = self._collect_qty()
        data['typo'] = self._collect_typo()
        return data

    def _typo_lines(self, key, product_id=False):
        """Líneas vigentes de Sage con ese nº de serie (dentro del filtro del asistente)."""
        Line = self.env['rms.sage.stock.line'].sudo()
        domain = self._base_domain() + [('is_current', '=', True), ('stock_kind', '=', 'stock'),
                                        ('serial_normalized', '=', key)]
        lines = Line.search(domain + ([('product_id', '=', product_id)] if product_id else []))
        return lines or Line.search(domain)

    def _collect_typo(self):
        """Hoja "Nº de serie mal escrito en Sage": lecturas emparejadas a mano
        con un nº de serie parecido de Sage y, en otra sección, las sugerencias
        del escáner que siguen sin confirmar."""
        Scan = self.env['rms.stock.count.scan'].sudo()
        head = ['Empresa', 'Almacén Sage', 'Artículo Sage', 'Nº de serie en Sage', 'Nº de serie leído en la etiqueta',
                'Quién lo confirmó', 'Cuándo', 'Recuento']
        base = [('session_id.state', '!=', 'cancel'), ('ignored', '=', False)]
        filtered = bool(self.sage_company_code or self.site_number)
        confirmed, seen = [], set()
        for scan in Scan.search(base + [('sage_match_state', '=', 'confirmed'), ('scan_type', '=', 'serial')],
                                order='sage_match_date, id'):
            mark = (scan.sage_match_key, scan.serial_normalized, scan.product_id.id)
            if mark in seen:
                continue  # la misma etiqueta leída por varios operarios
            seen.add(mark)
            lines = self._typo_lines(scan.sage_match_key, scan.product_id.id)
            if not lines and filtered:
                continue
            who = scan.sage_match_operator_id.name or scan.sage_match_user_id.name or ''
            for line in lines or [False]:
                confirmed.append([
                    COMPANY.get(line.sage_company_code, '') if line else '',
                    self._warehouse_label(line) if line else '(ya no está en las existencias de Sage)',
                    (line.article_code if line else '') or scan.product_id.default_code or '',
                    (line.serial if line else '') or scan.sage_match_serial or '',
                    scan.lot_name or scan.code or '', who, scan.sage_match_date, scan.session_id.name or ''])
        pending = []
        for scan in Scan.search(base + [('sage_match_state', '=', 'suggested')], order='scanned_at, id'):
            for candidate in scan.sage_match_candidates or []:
                for line in self._typo_lines(candidate['key'], candidate.get('product_id')):
                    pending.append([
                        COMPANY.get(line.sage_company_code, ''), self._warehouse_label(line), line.article_code or '',
                        line.serial or candidate.get('serial') or '', scan.lot_name or scan.code or '',
                        'POR CONFIRMAR (leído por %s)' % (scan.operator_id.name or ''), scan.scanned_at,
                        scan.session_id.name or ''])
        rows = list(confirmed)
        if pending:
            rows += [[''] * len(head),
                     ['POR CONFIRMAR: el escáner lo ha propuesto y nadie ha dicho todavía si es ese'] + [''] * (len(head) - 1)]
            rows += pending
        return (head, rows, len(confirmed), len(pending))

    def _collect_qty(self):
        """Hoja "Por cantidad": artículos sin nº de serie con diferencia o sin
        contar. Lo contado es de la nave entera (no se puede repartir por
        empresa): con filtro de empresa salen los artículos que esa empresa
        tiene en Sage, y lo contado que no está en Sage en ninguna."""
        Qty = self.env['rms.sage.checklist.qty'].sudo()
        domain = [('state', '!=', 'ok')]
        if self.site_number:
            domain.append(('site_number', '=', int(self.site_number)))
        if self.sage_company_code:
            domain += ['|', ('sage_qty_%s' % self.sage_company_code, '>', 0), ('state', '=', 'not_in_sage')]
        label = dict(Qty._fields['state'].selection)
        rows = [[r.site_name or 'Sin nave', r.brand_categ_id.name or '', r.default_code or '',
                 r.product_id.display_name or r.article_name or '', r.sage_qty, r.company_breakdown or '',
                 r.counted_qty, r.difference, label.get(r.state, '')]
                for r in Qty.search(domain)]
        return (['Nave', 'Marca', 'Referencia', 'Producto', 'Sage', 'Por empresa', 'Contado', 'Diferencia',
                 'Resultado'], rows)

    def _line_row(self, line):
        return [COMPANY.get(line.sage_company_code, ''), self._warehouse_label(line), line.brand_categ_id.name or '',
                line.article_code or '', line.article_name or line.product_id.display_name or '',
                SAGE_STATE.get(line.state, ''), line.serial or '']

    # ------------------------------------------------------------------
    def action_export(self):
        self.ensure_one()
        self.env['rms.sage.checklist'].check_access('read')
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter

        data = self._collect()
        book = Workbook()
        cover = book.active
        cover.title = 'Resumen'
        bold = Font(bold=True)
        fill = PatternFill('solid', fgColor='DDE3E9')
        scope = '%s · %s' % (COMPANY.get(self.sage_company_code, 'Las tres empresas'),
                             dict(SITES).get(self.site_number, 'Todas las naves'))
        now = fields.Datetime.context_timestamp(self, fields.Datetime.now())
        cover.append(['Descuadres entre el recuento y Sage'])
        cover['A1'].font = Font(bold=True, size=14)
        cover.append([scope])
        cover.append(['Generado el %s' % now.strftime('%d-%m-%Y %H:%M')])
        cover.append([])
        cover.append(['Hoja', 'Equipos', 'Qué significa y qué hay que hacer'])
        for cell in cover[5]:
            cell.font, cell.fill = bold, fill
        lines = []
        for key, title, help_text in SHEETS:
            head, rows = data[key][:2]
            if key == 'typo':
                # Las filas de la sección "por confirmar" no cuentan como descuadres ya vistos.
                cover.append([title, data[key][2], help_text])
                cover.append(['   … por confirmar', data[key][3],
                              'Sugerencias del escáner sin contestar («Sí, es este» / «No, es otro»).'])
                lines.append('%s: %d (por confirmar: %d)' % (title, data[key][2], data[key][3]))
            else:
                cover.append([title, len(rows), help_text])
                lines.append('%s: %d' % (title, len(rows)))
            sheet = book.create_sheet(title[:31])
            sheet.append(head)
            for cell in sheet[1]:
                cell.font, cell.fill = bold, fill
            for row in rows:
                sheet.append([self._cell(value) for value in row])
            sheet.freeze_panes = 'A2'
            if rows:
                sheet.auto_filter.ref = sheet.dimensions
            for index, column in enumerate(head, start=1):
                width = max([len(str(column))] + [len(str(r[index - 1] or '')) for r in rows[:500]])
                sheet.column_dimensions[get_column_letter(index)].width = min(max(width + 2, 10), 60)
        cover.column_dimensions['A'].width = 26
        cover.column_dimensions['B'].width = 10
        cover.column_dimensions['C'].width = 95
        for row in cover.iter_rows(min_row=6):
            row[2].alignment = Alignment(wrap_text=True, vertical='top')
        stream = io.BytesIO()
        book.save(stream)
        self.write({
            'file': base64.b64encode(stream.getvalue()),
            'filename': 'Descuadres_Sage_%s.xlsx' % now.strftime('%Y-%m-%d_%H%M'),
            'summary': '\n'.join(lines),
        })
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id,
                'view_mode': 'form', 'target': 'new'}

    def _cell(self, value):
        if value is False or value is None:
            return ''
        if hasattr(value, 'tzinfo'):  # datetime: a la hora del usuario y sin zona (Excel no la admite)
            return fields.Datetime.context_timestamp(self, value).replace(tzinfo=None)
        return value
