# -*- coding: utf-8 -*-
"""Carga de arranque del stock: la carga y sus líneas.

«Preparar» es una simulación (initial_load_plan.py): calcula qué entraría y
dónde, sin tocar el stock. «Aplicar» y «Deshacer» están en
initial_load_apply.py.
"""
import time
from collections import defaultdict

from markupsafe import Markup, escape

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

SITE_NAMES = {1: 'Madrid', 2: 'Nave 22', 3: 'Alfaomega', 4: 'Cataluña (Alex)', 5: 'Cataluña (Vicente)',
              6: 'Mallorca', 7: 'Sevilla'}
SAGE_COMPANIES = [('01', 'RMS'), ('02', 'Espacio'), ('03', 'RJB')]
SAGE_STATES = [('nuevo', 'Nuevo'), ('demo', 'Demo'), ('2mano', '2ª Mano')]
# Estado de Sage -> código del estado de Odoo. Sage solo distingue "demo"
# (prefijo D-): entra siempre como Demo, nunca como Ex-Demo.
SAGE_STATE_CODE = {'nuevo': 'new', 'demo': 'demo', '2mano': 'second_hand'}
KINDS = [
    ('counted', 'Contado'),
    ('sage_unverified', 'Según Sage, sin verificar'),
    ('alta', 'Alta (no está en Sage)'),
    ('phantom', 'Pendiente de localizar'),
    ('deposit', 'Depósito heredado de Sage'),
    ('qty_counted', 'Cantidad contada'),
    ('qty_sage', 'Cantidad de Sage sin verificar'),
    ('skip', 'No cargado'),
]
KIND_LABELS = dict(KINDS)
# Depósito de Sage del que ni la línea ni los movimientos dicen el cliente.
NO_PARTNER = '(sin nombre en Sage)'
KIND_HELP = {
    'counted': 'Equipos leídos con la pistola: entran en la nave donde se leyeron, a nombre de la empresa de Sage.',
    'sage_unverified': 'Equipos que nadie ha leído y entran según Sage, marcados «No verificado» (naves no '
                       'contadas, o comprados / devueltos / traspasados después del recuento).',
    'alta': 'Equipos leídos que no están en Sage: entran a nombre de RMS y quedan como «Alta por revisar».',
    'phantom': 'Sage los tiene en una nave contada y nadie los encontró: van al almacén fantasma '
               '«Pendiente de localizar» (no se pueden vender y no valoran).',
    'deposit': 'Equipos que Sage tiene en depósito en casa de un cliente: un depósito por cliente y empresa, '
               'sin verificar y sin firma.',
    'qty_counted': 'Artículos sin nº de serie contados en la nave, repartidos entre empresas hasta lo que dice Sage.',
    'qty_sage': 'Artículos sin nº de serie que nadie contó: entra la cantidad de Sage, sin verificar.',
    'skip': 'No se cargan. La nota de cada línea explica el motivo.',
}


class InitialLoad(models.Model):
    _name = 'rms.initial.load'
    _description = 'Carga de arranque del stock'
    _order = 'id desc'

    name = fields.Char(string='Nombre', required=True, default='Carga de arranque')
    date = fields.Date(string='Fecha de la carga', required=True, default=fields.Date.context_today)
    state = fields.Selection([
        ('draft', 'Borrador'), ('prepared', 'Preparada'), ('applied', 'Aplicada'), ('undone', 'Deshecha'),
    ], string='Situación', default='draft', required=True, copy=False, readonly=True)
    site_1 = fields.Boolean(string='Madrid')
    site_2 = fields.Boolean(string='Nave 22')
    site_3 = fields.Boolean(string='Alfaomega')
    site_4 = fields.Boolean(string='Cataluña (Alex)')
    site_5 = fields.Boolean(string='Cataluña (Vicente)')
    site_6 = fields.Boolean(string='Mallorca')
    site_7 = fields.Boolean(string='Sevilla')
    counted_sites_label = fields.Char(string='Naves contadas', compute='_compute_counted_sites_label')
    note = fields.Text(string='Notas')
    line_ids = fields.One2many('rms.initial.load.line', 'load_id', string='Líneas', copy=False)
    review_ids = fields.One2many('rms.initial.load.state.review', 'load_id', string='Revisión de estados', copy=False)
    cession_ids = fields.One2many('stock.cession', 'rms_initial_load_id', string='Depósitos creados')
    summary_html = fields.Html(string='Resumen', readonly=True, copy=False, sanitize=False)
    line_count = fields.Integer(string='Nº de líneas', compute='_compute_counters')
    unit_count = fields.Float(string='Unidades que entran', compute='_compute_counters')
    no_cost_units = fields.Float(string='Unidades sin coste', compute='_compute_counters')
    review_pending_count = fields.Integer(string='Estados por revisar', compute='_compute_counters')
    review_count = fields.Integer(string='Casos de estado', compute='_compute_counters')
    cession_count = fields.Integer(string='Depósitos', compute='_compute_counters')
    duplicate_count = fields.Integer(string='Ya estaban en Odoo', compute='_compute_counters')
    prepared_at = fields.Datetime(string='Preparada el', readonly=True, copy=False)
    prepared_by = fields.Many2one('res.users', string='Preparada por', readonly=True, copy=False)
    applied_at = fields.Datetime(string='Aplicada el', readonly=True, copy=False)
    applied_by = fields.Many2one('res.users', string='Aplicada por', readonly=True, copy=False)
    undone_at = fields.Datetime(string='Deshecha el', readonly=True, copy=False)
    undone_by = fields.Many2one('res.users', string='Deshecha por', readonly=True, copy=False)
    prepare_seconds = fields.Float(string='Segundos de preparar', readonly=True, copy=False, digits=(10, 1))
    apply_seconds = fields.Float(string='Segundos de aplicar', readonly=True, copy=False, digits=(10, 1))

    # ------------------------------------------------------------------
    def _counted_sites(self):
        self.ensure_one()
        return {number for number in SITE_NAMES if self['site_%d' % number]}

    @api.depends('site_1', 'site_2', 'site_3', 'site_4', 'site_5', 'site_6', 'site_7')
    def _compute_counted_sites_label(self):
        for load in self:
            load.counted_sites_label = ', '.join(SITE_NAMES[n] for n in sorted(load._counted_sites())) or 'Ninguna'

    @api.depends('line_ids.cost', 'line_ids.kind', 'line_ids.quantity', 'line_ids.apply_result',
                 'review_ids.state', 'cession_ids')
    def _compute_counters(self):
        Line = self.env['rms.initial.load.line']
        for load in self:
            entering = [('load_id', '=', load.id), ('kind', '!=', 'skip'), ('apply_result', '!=', 'duplicate')]
            load.line_count = Line.search_count([('load_id', '=', load.id)])
            totals = Line._read_group(entering, [], ['quantity:sum'])
            load.unit_count = totals[0][0] or 0.0
            # El fantasma no valora: su coste no cuenta como pendiente.
            no_cost = Line._read_group(entering + [('cost', '=', 0), ('kind', '!=', 'phantom')], [], ['quantity:sum'])
            load.no_cost_units = no_cost[0][0] or 0.0
            load.review_count = len(load.review_ids)
            load.review_pending_count = len(load.review_ids.filtered(lambda r: r.state == 'pending'))
            load.cession_count = len(load.cession_ids)
            load.duplicate_count = Line.search_count([('load_id', '=', load.id), ('apply_result', '=', 'duplicate')])

    def _check_manager(self):
        if not self.env.user.has_group('stock.group_stock_manager'):
            raise AccessError('Solo un responsable de inventario puede hacer la carga de arranque.')

    def write(self, vals):
        if any(key.startswith('site_') for key in vals) and any(load.state == 'applied' for load in self):
            raise UserError('La carga ya está aplicada: no se pueden cambiar las naves contadas.')
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_applied(self):
        if any(load.state == 'applied' for load in self):
            raise UserError('No se puede borrar una carga aplicada. Deshazla primero.')

    # ------------------------------------------------------------------ preparar
    def action_prepare(self):
        """Simulación: recalcula todas las líneas. No toca el stock."""
        self.ensure_one()
        self._check_manager()
        if self.state == 'applied':
            raise UserError('La carga ya está aplicada. Para recalcularla hay que deshacerla antes.')
        started = time.time()
        Line = self.env['rms.initial.load.line'].sudo()
        # Los costes ya puestos (a mano o desde Excel) se conservan al recalcular.
        self.env.cr.execute(
            "SELECT company_id, product_id, COALESCE(serial_normalized, ''), site_number, kind, cost "
            "  FROM rms_initial_load_line WHERE load_id = %s AND cost <> 0", [self.id])
        costs = {tuple(row[:5]): row[5] for row in self.env.cr.fetchall()}
        self.line_ids.sudo().unlink()
        vals_list = self.sudo()._plan_lines()
        review_by_key = self.sudo()._sync_reviews(vals_list)
        for vals in vals_list:
            review = review_by_key.get(vals.pop('_review_key', None))
            if review:
                vals['review_id'] = review.id
                if review.state == 'done':
                    vals['state_id'] = review.final_state_id.id
            key = (vals.get('company_id') or None, vals.get('product_id') or None,
                   vals.get('serial_normalized') or '', vals.get('site_number') or 0, vals['kind'])
            if key in costs:
                vals['cost'] = costs[key]
            vals['load_id'] = self.id
        for start in range(0, len(vals_list), 1000):
            Line.create(vals_list[start:start + 1000])
        self.sudo().write({
            'state': 'prepared', 'prepared_at': fields.Datetime.now(), 'prepared_by': self.env.user.id,
            'applied_at': False, 'applied_by': False, 'undone_at': False, 'undone_by': False,
            'apply_seconds': 0,
        })
        self.sudo()._refresh_summary()
        self.sudo().prepare_seconds = time.time() - started
        return True

    def action_back_to_draft(self):
        self.ensure_one()
        self._check_manager()
        if self.state == 'applied':
            raise UserError('La carga está aplicada: deshazla primero.')
        self.line_ids.sudo().unlink()
        self.review_ids.sudo().unlink()
        self.sudo().write({'state': 'draft', 'summary_html': False})
        return True

    def _sync_reviews(self, vals_list):
        """Crea o actualiza los casos de «Revisión de estados». Una decisión ya
        tomada se conserva al recalcular mientras la lectura y Sage sigan
        diciendo lo mismo. Devuelve {clave: caso}."""
        self.ensure_one()
        Review = self.env['rms.initial.load.state.review'].sudo()
        existing = {(review.product_id.id, review.serial_normalized): review for review in self.review_ids}
        result, to_create, seen = {}, [], set()
        for vals in vals_list:
            data = vals.pop('_review', None)
            if not data:
                continue
            key = (data['product_id'], data['serial_normalized'])
            vals['_review_key'] = key
            seen.add(key)
            review = existing.get(key)
            if review:
                changes = {name: value for name, value in data.items()
                           if (review[name].id if hasattr(review[name], 'id') else review[name]) != value}
                if 'sage_state' in changes or 'scanned_state_id' in changes:
                    changes.update(state='pending', final_state_id=False, reviewed_by=False, reviewed_on=False)
                if changes:
                    review.write(changes)
                result[key] = review
            else:
                to_create.append(dict(data, load_id=self.id))
        for review in Review.create(to_create):
            result[(review.product_id.id, review.serial_normalized)] = review
        (self.review_ids.filtered(lambda r: (r.product_id.id, r.serial_normalized) not in seen)).unlink()
        return result

    # ------------------------------------------------------------------ resumen
    def _summary_data(self):
        """{(nave, empresa): {tipo: unidades}} y totales por tipo."""
        self.ensure_one()
        Line = self.env['rms.initial.load.line'].sudo()
        table = defaultdict(lambda: defaultdict(float))
        totals = defaultdict(float)
        counts = defaultdict(int)
        for site, company, kind, quantity, count in Line._read_group(
                [('load_id', '=', self.id)], ['site_number', 'company_id', 'kind'], ['quantity:sum', '__count']):
            table[(site or 0, company)][kind] += quantity or 0.0
            totals[kind] += quantity or 0.0
            counts[kind] += count
        return table, totals, counts

    def _extra_figures(self):
        self.ensure_one()
        Line = self.env['rms.initial.load.line'].sudo()
        base = [('load_id', '=', self.id)]
        entering = base + [('kind', '!=', 'skip'), ('apply_result', '!=', 'duplicate')]

        def units(domain):
            return Line._read_group(domain, [], ['quantity:sum'])[0][0] or 0.0

        generic = self.env.ref('rms_stock_initial_load.partner_inherited_deposits', raise_if_not_found=False)
        unmatched = Line._read_group(
            base + [('kind', '=', 'deposit'), ('partner_id', '=', generic.id if generic else 0)],
            ['sage_partner_name'], ['__count'])
        return [
            ('Unidades que entran en total', units(entering)),
            ('Unidades sin coste (coste pendiente)', units(entering + [('cost', '=', 0), ('kind', '!=', 'phantom')])),
            ('Unidades «No verificado»', units(entering + [('unverified', '=', True)])),
            ('Estados por revisar uno a uno', len(self.review_ids.filtered(lambda r: r.state == 'pending'))),
            ('Depósitos a cerrar en Sage (leídos en la nave)', Line.search_count(base + [('deposit_to_close', '=', True)])),
            ('Clientes de depósito sin casar con un contacto', len(unmatched)),
            ('Depósitos heredados sin cliente identificado (equipos)',
             units(base + [('kind', '=', 'deposit'), ('sage_partner_name', '=', NO_PARTNER)])),
            ('Líneas con un movimiento de Sage posterior al recuento', Line.search_count(base + [('sage_move_id', '!=', False)])),
            ('Nº de serie que ya tenían existencias en Odoo (no duplicados)',
             Line.search_count(base + [('apply_result', '=', 'duplicate')])),
        ]

    def _refresh_summary(self):
        for load in self:
            table, totals, _counts = load._summary_data()
            head = ''.join('<th style="text-align:right">%s</th>' % escape(label) for _kind, label in KINDS)
            rows = []
            for (site, company), kinds in sorted(table.items(), key=lambda item: (item[0][0] or 99, item[0][1].id or 0)):
                cells = ''.join('<td style="text-align:right">%s</td>' % (_fmt(kinds.get(kind)) or '')
                                for kind, _label in KINDS)
                rows.append('<tr><td>%s</td><td>%s</td>%s</tr>' % (
                    escape(SITE_NAMES.get(site, 'Sin nave')), escape(company.name or '—'), cells))
            total = ''.join('<th style="text-align:right">%s</th>' % (_fmt(totals.get(kind)) or '0')
                            for kind, _label in KINDS)
            figures = ''.join('<tr><td>%s</td><td style="text-align:right"><b>%s</b></td></tr>' % (
                escape(label), _fmt(value) or '0') for label, value in load._extra_figures())
            load.summary_html = Markup(
                '<p><b>Naves contadas:</b> %s</p>'
                '<table class="table table-sm table-bordered o_rms_load_summary">'
                '<thead><tr><th>Nave</th><th>Empresa</th>%s</tr></thead><tbody>%s</tbody>'
                '<tfoot><tr><th colspan="2">Total (unidades)</th>%s</tr></tfoot></table>'
                '<table class="table table-sm" style="max-width:640px"><tbody>%s</tbody></table>'
            ) % (escape(load.counted_sites_label), Markup(head), Markup(''.join(rows)), Markup(total), Markup(figures))

    # ------------------------------------------------------------------ pantallas
    def _lines_action(self, name, domain=None, context=None):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('rms_stock_initial_load.action_initial_load_line')
        action.update(name=name, domain=[('load_id', '=', self.id)] + (domain or []),
                      context=dict(context or {}, default_load_id=self.id))
        return action

    def action_view_lines(self):
        return self._lines_action('Líneas de la carga', context={'search_default_group_kind': 1})

    def action_view_no_cost(self):
        return self._lines_action('Unidades sin coste', [('kind', 'not in', ('skip', 'phantom')), ('cost', '=', 0)])

    def action_view_duplicates(self):
        return self._lines_action('Ya tenían existencias en Odoo', [('apply_result', '=', 'duplicate')])

    def action_view_reviews(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('rms_stock_initial_load.action_state_review')
        action.update(domain=[('load_id', '=', self.id)], context={'search_default_pending': 1})
        return action

    def action_view_cessions(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('rms_stock_delivery_check.action_deposit')
        action.update(domain=[('rms_initial_load_id', '=', self.id)], context={})
        return action

    def action_import_costs(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Cargar costes desde Excel',
                'res_model': 'rms.initial.load.cost.import', 'view_mode': 'form', 'target': 'new',
                'context': {'default_load_id': self.id}}

    def action_use_sage_cost(self):
        """Pone en las líneas sin coste el coste de su línea de Sage."""
        self.ensure_one()
        self._check_manager()
        if self.state != 'prepared':
            raise UserError('Los costes se ponen con la carga preparada y antes de aplicarla.')
        self.env['rms.initial.load.line'].flush_model()
        self.env.cr.execute(
            'UPDATE rms_initial_load_line SET cost = sage_cost '
            ' WHERE load_id = %s AND COALESCE(cost, 0) = 0 AND COALESCE(sage_cost, 0) > 0', [self.id])
        count = self.env.cr.rowcount
        self.env['rms.initial.load.line'].invalidate_model(['cost'])
        self.invalidate_recordset()
        self.sudo()._refresh_summary()
        return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
            'type': 'success', 'message': 'Coste de Sage puesto en %d líneas.' % count,
            'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'}}}


def _fmt(value):
    if not value:
        return ''
    return ('%.3f' % value).rstrip('0').rstrip('.')


class InitialLoadLine(models.Model):
    _name = 'rms.initial.load.line'
    _description = 'Línea de la carga de arranque'
    _order = 'site_number, company_id, kind, product_id, lot_name, id'
    _rec_name = 'lot_name'

    load_id = fields.Many2one('rms.initial.load', string='Carga', required=True, ondelete='cascade', index=True)
    load_state = fields.Selection(related='load_id.state', string='Situación de la carga')
    kind = fields.Selection(KINDS, string='Tipo', required=True, index=True)
    company_id = fields.Many2one('res.company', string='Empresa', index=True)
    sage_company_code = fields.Selection(SAGE_COMPANIES, string='Empresa Sage')
    site_number = fields.Integer(string='Nº de nave', aggregator=False, index=True)
    site_name = fields.Char(string='Nave', compute='_compute_site_name', store=True)
    location_id = fields.Many2one('stock.location', string='Ubicación de destino')
    destination = fields.Char(string='Entra en', compute='_compute_destination')
    product_id = fields.Many2one('product.product', string='Producto', index=True)
    article_code = fields.Char(string='Artículo Sage')
    lot_name = fields.Char(string='Nº de serie')
    serial_normalized = fields.Char(index=True)
    state_id = fields.Many2one('product.state', string='Estado final')
    quantity = fields.Float(string='Cantidad', default=1.0, digits='Product Unit')
    cost = fields.Float(string='Coste unitario', digits='Product Price',
                        help='Vacío (0) = coste pendiente. No bloquea la carga.')
    sage_cost = fields.Float(string='Coste en Sage', digits='Product Price', readonly=True)
    cost_pending = fields.Boolean(string='Coste pendiente', compute='_compute_cost_pending',
                                  search='_search_cost_pending')
    unverified = fields.Boolean(string='No verificado', index=True)
    note = fields.Char(string='Motivo')
    scan_id = fields.Many2one('rms.stock.count.scan', string='Lectura', ondelete='set null')
    session_id = fields.Many2one('rms.stock.count.session', string='Recuento', ondelete='set null')
    scanned_at = fields.Datetime(string='Leído el')
    sage_line_id = fields.Many2one('rms.sage.stock.line', string='Línea de Sage', ondelete='set null')
    sage_warehouse_code = fields.Char(string='Almacén Sage')
    sage_state = fields.Selection(SAGE_STATES, string='Estado en Sage')
    sage_qty = fields.Float(string='Cantidad en Sage', digits='Product Unit')
    counted_qty = fields.Float(string='Contado en la nave', digits='Product Unit')
    partner_id = fields.Many2one('res.partner', string='Cliente del depósito')
    sage_partner_name = fields.Char(string='Cliente según Sage')
    deposit_date = fields.Date(string='Fecha del depósito en Sage')
    deposit_to_close = fields.Boolean(string='Depósito a cerrar en Sage', index=True)
    sage_move_id = fields.Many2one('rms.sage.serial.move', string='Movimiento de Sage aplicado', ondelete='set null')
    review_id = fields.Many2one('rms.initial.load.state.review', string='Revisión de estado', ondelete='set null',
                                index='btree_not_null')
    review_state = fields.Selection(related='review_id.state', string='Revisión')
    # Resultado de «Aplicar»
    apply_result = fields.Selection([
        ('pending', 'Sin aplicar'), ('done', 'Cargado'), ('duplicate', 'Ya tenía existencias: no duplicado'),
        ('undone', 'Deshecho'),
    ], string='Resultado', default='pending', required=True, index=True, copy=False)
    lot_id = fields.Many2one('stock.lot', string='Nº de serie en Odoo', copy=False, ondelete='set null')
    lot_created = fields.Boolean(copy=False)
    move_id = fields.Many2one('stock.move', string='Movimiento de entrada', copy=False, ondelete='set null')
    undo_move_id = fields.Many2one('stock.move', string='Movimiento de deshacer', copy=False, ondelete='set null')
    cession_id = fields.Many2one('stock.cession', string='Depósito creado', copy=False, ondelete='set null')

    @api.depends('site_number')
    def _compute_site_name(self):
        for line in self:
            line.site_name = SITE_NAMES.get(line.site_number) or 'Sin nave'

    @api.depends('kind', 'location_id', 'partner_id', 'sage_partner_name')
    def _compute_destination(self):
        for line in self:
            if line.kind == 'skip':
                line.destination = 'No se carga'
            elif line.kind == 'phantom':
                line.destination = 'Pendiente de localizar (%s)' % (line.company_id.name or '')
            elif line.kind == 'deposit':
                line.destination = 'Depósito en %s' % (line.sage_partner_name or line.partner_id.name or 'cliente')
            else:
                line.destination = line.location_id.display_name or ''

    @api.depends('cost', 'kind')
    def _compute_cost_pending(self):
        for line in self:
            line.cost_pending = line.kind not in ('skip', 'phantom') and not line.cost

    def _search_cost_pending(self, operator, value):
        if operator not in ('=', '!=') or not isinstance(value, bool):
            return NotImplemented
        if (operator == '=') == value:
            return [('kind', 'not in', ('skip', 'phantom')), ('cost', '=', 0)]
        return ['|', ('kind', 'in', ('skip', 'phantom')), ('cost', '!=', 0)]

    def write(self, vals):
        if not self.env.su and set(vals) - {'cost'}:
            raise UserError('Las líneas las calcula «Preparar». Solo se puede cambiar el coste.')
        if 'cost' in vals and any(line.load_id.state not in ('draft', 'prepared') for line in self):
            raise UserError('La carga ya está aplicada: el coste ya no se puede cambiar aquí.')
        return super().write(vals)
