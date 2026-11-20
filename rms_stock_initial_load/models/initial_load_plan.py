# -*- coding: utf-8 -*-
"""Simulación de la carga de arranque: qué entra, dónde y por qué.

Solo lee (lecturas de los recuentos, existencias y movimientos de Sage) y
devuelve los valores de las líneas. Reglas del 20-nov-2026:

 1. Manda lo contado; lo no encontrado en una nave contada -> fantasma.
 2. Nave no contada -> según Sage, «No verificado».
 3. Destino: la ubicación general de la nave de la empresa dueña.
 4. Empresa: la de Sage; las altas, a RMS.
 5. Estado distinto entre lectura y Sage -> revisión uno a uno.
 6. Depósitos de Sage -> un depósito por cliente y empresa.
 7. Por cantidad: lo contado se reparte entre empresas (RMS, Espacio, RJB).
 8. Movimientos de Sage posteriores al recuento, aplicados sobre lo contado.
 9. Almacenes de Sage sin nave: no se cargan.
"""
import re
import unicodedata
from collections import Counter, defaultdict

from odoo import fields, models
from odoo.exceptions import UserError

from odoo.addons.rms_stock_count_session.models.sage_expected import normalize_serial, serial_alternatives
from odoo.addons.rms_stock_count_session.models.sage_live import SHORT_LABELS

from .initial_load import SAGE_STATE_CODE, SITE_NAMES

COMPANY_ORDER = ['01', '02', '03']
ODOO_PREFIX = {'01': 'RMS', '02': 'ET', '03': 'RJB'}
COMPANY_LABEL = {'01': 'RMS', '02': 'Espacio', '03': 'RJB'}
STATE_LABEL = {'nuevo': 'Nuevo', 'demo': 'Demo', '2mano': '2ª Mano'}
_LEGAL_FORMS = {'SL', 'SA', 'SLU', 'SAU', 'SLL', 'SC', 'CB', 'SCP', 'SLP', 'SCOOP', 'SCA'}


def normalize_partner_name(name):
    """Nombre de cliente comparable: sin acentos, mayúsculas, sin signos y sin
    la forma jurídica final (S.L., S.A., S.L.U....)."""
    text = unicodedata.normalize('NFKD', name or '')
    text = ''.join(char for char in text if not unicodedata.combining(char)).upper()
    text = re.sub(r'(?<=\b[A-Z])\.(?=[A-Z]\b)', '', text)  # S.L. -> SL.
    words = re.sub(r'[^A-Z0-9]+', ' ', text).split()
    while len(words) > 1 and words[-1] in _LEGAL_FORMS:
        words.pop()
    return ''.join(words)


def _date(value):
    return value.strftime('%d-%m-%Y') if value else ''


class InitialLoad(models.Model):
    _inherit = 'rms.initial.load'

    # ------------------------------------------------------------------ datos
    def _plan_context(self):
        """Todo lo que la simulación necesita, leído de una vez."""
        env = self.env
        cr = env.cr
        for model in ('rms.sage.stock.line', 'rms.sage.warehouse', 'rms.sage.serial.move',
                      'rms.stock.count.scan', 'rms.stock.count.session', 'stock.location', 'stock.warehouse'):
            env[model].flush_model()
        ctx = {'counted_sites': self._counted_sites()}
        ctx['states'] = {state.code: state.id for state in env['product.state'].search([])}
        ctx['state_code'] = {state_id: code for code, state_id in ctx['states'].items()}
        ctx['state_name'] = {state.id: state.name for state in env['product.state'].search([])}

        # Almacenes de Sage -> nave, ubicación y empresa de Odoo.
        wh_site, loc_by, wh_by_code, companies = {}, {}, {}, defaultdict(Counter)
        for warehouse in env['rms.sage.warehouse'].search([]):
            main = warehouse.alias_of_id or warehouse
            location = main.location_id
            site = main.site_number if location else 0
            wh_site[warehouse.id] = site
            wh_by_code[(warehouse.sage_company_code, (warehouse.code or '').strip().upper())] = site
            if site and location:
                loc_by.setdefault((warehouse.sage_company_code, site), location.id)
                companies[warehouse.sage_company_code][location.company_id.id] += 1
        ctx.update(wh_site=wh_site, wh_by_code=wh_by_code, loc_by=loc_by)
        company_by_code = {}
        for code in COMPANY_ORDER:
            if companies[code]:
                company_by_code[code] = companies[code].most_common(1)[0][0]
            else:
                # Sin almacenes enlazados: el almacén de Odoo RMSn / ETn / RJBn, o la empresa de la versión de Sage.
                warehouse = env['stock.warehouse'].with_context(active_test=False).search(
                    [('code', '=like', ODOO_PREFIX[code] + '%')], limit=1)
                company_by_code[code] = (warehouse.company_id or env['rms.sage.sync.run']._company_for(code)).id
        ctx['company_by_code'] = company_by_code
        ctx['location_company'] = {}

        # Existencias vigentes de Sage.
        cr.execute("""
            SELECT l.id, l.sage_company_code, l.stock_kind, COALESCE(l.in_deposit, FALSE), l.warehouse_code,
                   l.sage_warehouse_id, l.article_code, COALESCE(l.model_normalized, ''), l.state, l.serial,
                   COALESCE(l.serial_normalized, ''), l.quantity, COALESCE(l.cost, 0), l.product_id, l.partner_name
              FROM rms_sage_stock_line l
             WHERE l.is_current
             ORDER BY l.stock_kind DESC, l.id""")
        keys = ('id', 'code', 'stock_kind', 'in_deposit', 'warehouse_code', 'warehouse_id', 'article', 'model',
                'state', 'serial', 'sn', 'quantity', 'cost', 'product_id', 'partner_name')
        ctx['sage_rows'] = [dict(zip(keys, row)) for row in cr.fetchall()]

        # Lecturas válidas con su nave (nº final del código del almacén de Odoo).
        cr.execute("""
            SELECT sc.id, sc.session_id, sc.scan_type, sc.product_id, COALESCE(sc.lot_name, sc.code),
                   COALESCE(sc.serial_normalized, ''), sc.product_state_id, sc.scanned_at, sc.quantity,
                   COALESCE(substring(btrim(wh.code) from '[0-9]+$')::int, 0)
              FROM rms_stock_count_scan sc
              JOIN rms_stock_count_session ss ON ss.id = sc.session_id
              LEFT JOIN stock_location loc ON loc.id = COALESCE(sc.location_id, ss.location_id)
              LEFT JOIN stock_warehouse wh ON wh.id = loc.warehouse_id
             WHERE ss.state <> 'cancel' AND NOT COALESCE(sc.ignored, FALSE)
               AND sc.scan_type IN ('serial', 'unknown', 'product')
             ORDER BY sc.scanned_at, sc.id""")
        keys = ('id', 'session_id', 'scan_type', 'product_id', 'lot_name', 'sn', 'state_id', 'scanned_at',
                'quantity', 'site')
        ctx['scan_rows'] = [dict(zip(keys, row)) for row in cr.fetchall()]

        # Inicio del recuento de cada nave: primera lectura (o apertura del recuento).
        cr.execute("""
            SELECT COALESCE(substring(btrim(wh.code) from '[0-9]+$')::int, 0),
                   min(LEAST(COALESCE(ss.date_start, ss.create_date),
                             (SELECT min(sc.scanned_at) FROM rms_stock_count_scan sc WHERE sc.session_id = ss.id)))
              FROM rms_stock_count_session ss
              JOIN stock_location loc ON loc.id = ss.location_id
              LEFT JOIN stock_warehouse wh ON wh.id = loc.warehouse_id
             WHERE ss.state <> 'cancel'
             GROUP BY 1""")
        ctx['count_start'] = {site: value.date() for site, value in cr.fetchall() if value}

        # Movimientos de Sage por nº de serie, del más reciente al más antiguo.
        cr.execute("""
            SELECT id, serial_normalized, move_type, move_date, warehouse_from, warehouse_to, document,
                   partner_name, sage_company_code
              FROM rms_sage_serial_move
             WHERE move_date IS NOT NULL AND COALESCE(serial_normalized, '') <> ''
             ORDER BY move_date DESC, id DESC""")
        moves = defaultdict(list)
        keys = ('id', 'sn', 'type', 'date', 'wh_from', 'wh_to', 'document', 'partner_name', 'code')
        for row in cr.fetchall():
            moves[row[1]].append(dict(zip(keys, row)))
        ctx['moves'] = moves

        product_ids = {row['product_id'] for row in ctx['sage_rows'] if row['product_id']}
        product_ids |= {row['product_id'] for row in ctx['scan_rows'] if row['product_id']}
        ctx['tracking'] = {}
        Product = env['product.product'].with_context(active_test=False)
        for start in range(0, len(product_ids), 2000):
            for product in Product.browse(list(product_ids)[start:start + 2000]).read(['tracking', 'is_storable']):
                ctx['tracking'][product['id']] = product['tracking'] if product['is_storable'] else 'no_stock'
        ctx['partners'] = None
        return ctx

    def _plan_location(self, ctx, code, site):
        """Ubicación general de la nave para esa empresa de Sage (RMS7/Stock...)."""
        key = (code, site)
        if key not in ctx['loc_by']:
            warehouse = self.env['stock.warehouse'].with_context(active_test=False).search(
                [('code', '=', '%s%d' % (ODOO_PREFIX.get(code, ''), site))], limit=1) if site else False
            ctx['loc_by'][key] = warehouse.lot_stock_id.id if warehouse else False
        return ctx['loc_by'][key]

    def _plan_partner(self, ctx, name):
        """Contacto de un cliente de Sage por nombre normalizado: solo si hay una
        coincidencia única. Si no, el contacto genérico (no se crean clientes)."""
        if ctx['partners'] is None:
            index = defaultdict(list)
            self.env.cr.execute(
                "SELECT id, COALESCE(NULLIF(name, ''), complete_name), parent_id FROM res_partner WHERE active")
            for partner_id, partner_name, parent_id in self.env.cr.fetchall():
                key = normalize_partner_name(partner_name)
                if key:
                    index[key].append((partner_id, parent_id))
            ctx['partners'] = index
            ctx['generic_partner'] = self.env.ref('rms_stock_initial_load.partner_inherited_deposits').id
        found = ctx['partners'].get(normalize_partner_name(name), [])
        if len(found) > 1:
            # Varios con el mismo nombre: vale si solo uno es la empresa (sin contacto padre).
            found = [item for item in found if not item[1]]
        if len(found) == 1:
            return found[0][0], True
        return ctx['generic_partner'], False

    @staticmethod
    def _plan_latest_move(ctx, serial_keys, since, types=None):
        best = None
        for key in serial_keys:
            for move in ctx['moves'].get(key, ()):
                if since and move['date'] < since:
                    break
                if types and move['type'] not in types:
                    continue
                if best is None or (move['date'], move['id']) > (best['date'], best['id']):
                    best = move
                break
        return best

    @staticmethod
    def _plan_move_label(move):
        text = SHORT_LABELS.get(move['type'], move['type'])
        if move['partner_name'] and move['type'] in ('sale', 'deposit', 'deposit_return'):
            text += (' de ' if move['type'] == 'deposit_return' else ' a ') + move['partner_name'].strip()
        if move['type'] == 'transfer':
            text += ' %s → %s' % (move['wh_from'] or '?', move['wh_to'] or '?')
        text += ' el %s' % _date(move['date'])
        if move['document']:
            text += ' (doc. %s)' % move['document']
        return text

    # ------------------------------------------------------------------ plan
    def _plan_lines(self):
        self.ensure_one()
        ctx = self._plan_context()
        counted_sites = ctx['counted_sites']
        missing = sorted(site for site in counted_sites if site not in {row['site'] for row in ctx['scan_rows']})
        if missing:
            raise UserError(
                'Estas naves están marcadas como contadas pero no tienen ninguna lectura: %s.\n'
                'Si se cargaran así, todo lo que Sage tiene en ellas iría a «Pendiente de localizar». '
                'Desmárcalas o termina antes su recuento.' % ', '.join(SITE_NAMES[site] for site in missing))
        lines = []
        used_serials = {}
        self._plan_serials(ctx, lines, used_serials)
        self._plan_quantities(ctx, lines)
        return lines

    def _plan_serials(self, ctx, lines, used_serials):
        states, state_code, tracking = ctx['states'], ctx['state_code'], ctx['tracking']
        counted_sites = ctx['counted_sites']
        load_date = self.date

        # --- Unidades de Sage con nº de serie (existencias + depósitos de venta) ---
        units, by_key, sage_by_sn, all_sage_sn = [], defaultdict(list), defaultdict(list), set()

        def index_unit(unit):
            # Sage guarda a veces "SN" delante (AtlasIED) y la etiqueta no, o al revés.
            for serial_key in [unit['sn']] + serial_alternatives(unit['sn']):
                sage_by_sn[serial_key].append(unit)

        for row in ctx['sage_rows']:
            if row['sn'] in ('', 'SN'):
                continue
            all_sage_sn.add(row['sn'])
            all_sage_sn.update(serial_alternatives(row['sn']))
            if row['quantity'] <= 0:
                continue
            key = (row['code'], row['sn'], row['model'])
            if row['stock_kind'] == 'stock':
                unit = {'code': row['code'], 'sn': row['sn'], 'stock': row, 'deposit': None, 'group': None}
                by_key[key].append(unit)
                units.append(unit)
                index_unit(unit)
            else:
                # Depósito de venta: se une a su existencia (Sage la cuenta en las dos listas).
                target = next((u for u in by_key.get(key, ()) if not u['deposit']), None)
                if target:
                    target['deposit'] = row
                else:
                    unit = {'code': row['code'], 'sn': row['sn'], 'stock': None, 'deposit': row, 'group': None}
                    by_key[key].append(unit)
                    units.append(unit)
                    index_unit(unit)
        for unit in units:
            stock, deposit = unit['stock'], unit['deposit']
            base = stock or deposit
            unit.update(
                product_id=(stock and stock['product_id']) or (deposit and deposit['product_id']) or False,
                site=ctx['wh_site'].get(stock['warehouse_id'], 0) if stock else 0,
                in_deposit=bool(deposit) or bool(stock and stock['in_deposit']),
                partner_name=((deposit and deposit['partner_name']) or (stock and stock['partner_name']) or '').strip(),
                state=base['state'], serial=(base['serial'] or '').strip(), article=base['article'],
                cost=(stock and stock['cost']) or (deposit and deposit['cost']) or 0.0,
                warehouse_code=base['warehouse_code'], line_id=base['id'],
            )

        # --- Lecturas agrupadas por nº de serie y producto (la última manda) ---
        groups = {}
        for scan in ctx['scan_rows']:
            if scan['scan_type'] == 'product' or not scan['sn']:
                continue
            product_id = scan['product_id'] if scan['scan_type'] == 'serial' and scan['product_id'] else 0
            group = groups.get((scan['sn'], product_id))
            if not group:
                group = groups[(scan['sn'], product_id)] = {
                    'sn': scan['sn'], 'product_id': product_id, 'first_at': scan['scanned_at'], 'unit': None}
            group.update(scan_id=scan['id'], session_id=scan['session_id'], last_at=scan['scanned_at'],
                         site=scan['site'], state_id=scan['state_id'], lot_name=(scan['lot_name'] or '').strip())
        typed_sn = {sn for (sn, product_id) in groups if product_id}

        def add(kind, **vals):
            vals['kind'] = kind
            if vals.get('company_code'):
                vals['sage_company_code'] = vals['company_code']
            vals.pop('company_code', None)
            serial = vals.get('lot_name')
            if serial:
                vals['serial_normalized'] = normalize_serial(serial)
            if kind != 'skip' and serial and vals.get('product_id'):
                key = (vals['product_id'], vals['serial_normalized'])
                if key in used_serials:
                    vals.pop('_review', None)
                    vals.update(kind='skip', location_id=False, unverified=False, note=(
                        'Nº de serie repetido en Sage: ya entra por otra línea (%s). No se carga dos veces.'
                        % used_serials[key]))
                else:
                    used_serials[key] = '%s, %s' % (
                        COMPANY_LABEL.get(vals.get('sage_company_code'), ''), SITE_NAMES.get(vals.get('site_number'), 'sin nave'))
            if vals['kind'] == 'skip':
                vals.update(location_id=False, unverified=False)
            if vals.get('sage_company_code') and not vals.get('company_id'):
                vals['company_id'] = ctx['company_by_code'].get(vals['sage_company_code'])
            lines.append(vals)
            return vals

        def group_vals(group):
            return {'scan_id': group['scan_id'], 'session_id': group['session_id'], 'scanned_at': group['last_at']}

        def unit_vals(unit):
            return {'sage_company_code': unit['code'], 'sage_line_id': unit['line_id'], 'article_code': unit['article'],
                    'sage_warehouse_code': unit['warehouse_code'], 'sage_state': unit['state'],
                    'sage_cost': unit['cost'], 'sage_qty': 1.0}

        def deposit_vals(unit_or_code, partner_name, keys, date=None, move=None):
            partner_name = (partner_name or '').strip()
            partner_id, _matched = self._plan_partner(ctx, partner_name)
            if not date:
                last = self._plan_latest_move(ctx, keys, None, types=('deposit',))
                date = last['date'] if last else None
            return {'partner_id': partner_id, 'sage_partner_name': partner_name or '(sin nombre en Sage)',
                    'deposit_date': date or load_date, 'unverified': True}

        def tracked_problem(product_id):
            kind = tracking.get(product_id)
            if kind == 'none':
                return 'El producto no lleva nº de serie en Odoo: actívalo en el producto. No se carga.'
            if kind == 'no_stock':
                return 'El producto no es almacenable en Odoo. No se carga.'
            return ''

        # --- Cada lectura se casa con una unidad de Sage ---
        for group in sorted((g for g in groups.values() if g['product_id']), key=lambda g: (g['first_at'], g['scan_id'])):
            keys = [group['sn']] + serial_alternatives(group['sn'])
            candidates = list({id(unit): unit for key in keys for unit in sage_by_sn.get(key, ())
                               if unit['group'] is None
                               and (not unit['product_id'] or unit['product_id'] == group['product_id'])}.values())
            if candidates:
                unit = min(candidates, key=lambda u: (u['site'] != group['site'], u['in_deposit'], u['code'], u['line_id']))
                unit['group'], group['unit'] = group, unit

        # --- Unidades de Sage ---
        for unit in units:
            group = unit['group']
            code = unit['code']
            product_id = unit['product_id'] or (group and group['product_id']) or False
            keys = [unit['sn']] + serial_alternatives(unit['sn'])
            if group:
                keys = list(dict.fromkeys(keys + [group['sn']] + serial_alternatives(group['sn'])))
            base = dict(unit_vals(unit), product_id=product_id, quantity=1.0,
                        lot_name=(group['lot_name'] if group else unit['serial']) or unit['serial'],
                        state_id=states.get(SAGE_STATE_CODE.get(unit['state'], 'new')))
            if group:
                base.update(group_vals(group))
            if not product_id:
                add('skip', site_number=unit['site'], note='El artículo de Sage %s no tiene producto en Odoo. No se carga.'
                    % unit['article'], **base)
                continue
            problem = tracked_problem(product_id)
            if problem:
                add('skip', site_number=unit['site'], note=problem, **base)
                continue

            if group:
                since = group['first_at'].date()
                move = self._plan_latest_move(ctx, keys, since)
                read_on = _date(group['last_at'])
                site_label = SITE_NAMES.get(group['site'], 'una ubicación sin nave')
                if group['state_id']:
                    base['state_id'] = group['state_id']
                review = None
                if group['state_id'] and state_code.get(group['state_id']) != SAGE_STATE_CODE.get(unit['state']):
                    review = {
                        'product_id': product_id, 'serial_normalized': normalize_serial(base['lot_name']),
                        'serial': base['lot_name'], 'site_number': group['site'],
                        'company_id': ctx['company_by_code'].get(code), 'sage_state': unit['state'],
                        'scanned_state_id': group['state_id'], 'scan_id': group['scan_id'],
                        'session_id': group['session_id'], 'sage_line_id': unit['line_id'],
                    }
                if move and move['type'] == 'sale':
                    add('skip', site_number=group['site'], sage_move_id=move['id'], note=(
                        'Leído el %s en %s y después vendido en Sage: %s. No entra.'
                        % (read_on, site_label, self._plan_move_label(move))), **base)
                    continue
                if move and move['type'] == 'deposit':
                    add('deposit', site_number=group['site'], sage_move_id=move['id'], _review=review, note=(
                        'Leído el %s en %s y después dejado en depósito en Sage: %s. Entra en el depósito de ese cliente.'
                        % (read_on, site_label, self._plan_move_label(move))),
                        **dict(base, **deposit_vals(unit, move['partner_name'] or unit['partner_name'], keys, date=move['date'])))
                    continue
                if move and move['type'] == 'transfer':
                    dest_site = ctx['wh_by_code'].get((code, (move['wh_to'] or '').strip().upper()), 0)
                    if dest_site != group['site']:
                        location = self._plan_location(ctx, code, dest_site)
                        if not location:
                            add('skip', site_number=0, sage_move_id=move['id'], note=(
                                'Leído el %s en %s y después traspasado en Sage a un almacén sin nave: %s. '
                                'Sin ubicar, no cargado.' % (read_on, site_label, self._plan_move_label(move))), **base)
                        else:
                            add('sage_unverified', site_number=dest_site, location_id=location, unverified=True,
                                sage_move_id=move['id'], _review=review, note=(
                                    'Leído el %s en %s y después traspasado en Sage: %s. Entra en la nave de destino, '
                                    'sin verificar.' % (read_on, site_label, self._plan_move_label(move))), **base)
                        continue
                location = self._plan_location(ctx, code, group['site'])
                if not location:
                    add('skip', site_number=group['site'], note=(
                        'Leído el %s en una ubicación que no es de ninguna nave (o la empresa %s no tiene almacén '
                        'en %s). No se carga.' % (read_on, COMPANY_LABEL.get(code, code), site_label)), **base)
                    continue
                note = 'Leído el %s en %s.' % (read_on, site_label)
                if unit['in_deposit']:
                    note += ' Sage lo tiene en depósito en %s: DEPÓSITO A CERRAR EN SAGE.' % (
                        unit['partner_name'] or 'un cliente')
                elif not unit['site']:
                    note += ' Sage lo tiene en un almacén sin nave (%s).' % unit['warehouse_code']
                elif unit['site'] != group['site']:
                    note += ' Sage lo tiene en %s.' % SITE_NAMES.get(unit['site'], unit['warehouse_code'])
                if move and move['type'] == 'transfer':
                    note += ' Traspasado en Sage a esta nave (%s).' % self._plan_move_label(move)
                if review:
                    note += ' Estado distinto al de Sage (%s): revisar.' % STATE_LABEL.get(unit['state'], unit['state'])
                add('counted', site_number=group['site'], location_id=location, _review=review, note=note,
                    deposit_to_close=unit['in_deposit'], sage_move_id=move['id'] if move and move['type'] == 'transfer' else False,
                    **dict(base, sage_partner_name=unit['partner_name'] if unit['in_deposit'] else False))
                continue

            # --- No leído ---
            if unit['in_deposit']:
                add('deposit', site_number=unit['site'], note=(
                    'Sage lo tiene en depósito en %s. Entra en el depósito de ese cliente, sin verificar.'
                    % (unit['partner_name'] or 'un cliente sin nombre')),
                    **dict(base, **deposit_vals(unit, unit['partner_name'], keys)))
                continue
            if not unit['site']:
                add('skip', site_number=0, note='Almacén de Sage sin nave (%s): sin ubicar, no cargado.'
                    % unit['warehouse_code'], **base)
                continue
            location = self._plan_location(ctx, code, unit['site'])
            site_label = SITE_NAMES.get(unit['site'], unit['warehouse_code'])
            if not location:
                add('skip', site_number=unit['site'], note='La empresa %s no tiene almacén de Odoo en %s. No se carga.'
                    % (COMPANY_LABEL.get(code, code), site_label), **base)
                continue
            if unit['site'] not in counted_sites:
                add('sage_unverified', site_number=unit['site'], location_id=location, unverified=True,
                    note='Nave no contada (%s): entra según Sage, sin verificar.' % site_label, **base)
                continue
            start = ctx['count_start'].get(unit['site'])
            move = self._plan_latest_move(ctx, keys, start) if start else None
            if move and move['type'] in ('purchase', 'deposit_return'):
                add('sage_unverified', site_number=unit['site'], location_id=location, unverified=True,
                    sage_move_id=move['id'], note=(
                        'No leído, pero entró después del recuento de %s: %s. Entra en la nave, sin verificar.'
                        % (site_label, self._plan_move_label(move))), **base)
            elif move and move['type'] == 'transfer':
                dest_site = ctx['wh_by_code'].get((code, (move['wh_to'] or '').strip().upper()), 0) or unit['site']
                dest_location = self._plan_location(ctx, code, dest_site) or location
                add('sage_unverified', site_number=dest_site, location_id=dest_location, unverified=True,
                    sage_move_id=move['id'], note=(
                        'No leído, pero traspasado después del recuento: %s. Entra en la nave de destino, sin verificar.'
                        % self._plan_move_label(move)), **base)
            elif move and move['type'] == 'sale':
                add('skip', site_number=unit['site'], sage_move_id=move['id'], note=(
                    'No leído y vendido después del recuento según Sage: %s. No entra.'
                    % self._plan_move_label(move)), **base)
            elif move and move['type'] == 'deposit':
                add('deposit', site_number=unit['site'], sage_move_id=move['id'], note=(
                    'No leído y dejado en depósito después del recuento: %s. Entra en el depósito de ese cliente.'
                    % self._plan_move_label(move)),
                    **dict(base, **deposit_vals(unit, move['partner_name'], keys, date=move['date'])))
            else:
                add('phantom', site_number=unit['site'], note=(
                    'Sage lo tiene en %s y nadie lo ha leído: va a «Pendiente de localizar».' % site_label), **base)

        # --- Lecturas que no casan con ninguna unidad de Sage ---
        for group in sorted(groups.values(), key=lambda g: (g['first_at'], g['scan_id'])):
            if group['unit']:
                continue
            keys = [group['sn']] + serial_alternatives(group['sn'])
            base = dict(group_vals(group), product_id=group['product_id'] or False, quantity=1.0,
                        lot_name=group['lot_name'], site_number=group['site'],
                        state_id=group['state_id'] or states.get('new'))
            read_on = _date(group['last_at'])
            site_label = SITE_NAMES.get(group['site'], 'una ubicación sin nave')
            in_sage = any(key in all_sage_sn for key in keys)
            if not group['product_id']:
                if group['sn'] in typed_sn or any(key in typed_sn for key in keys):
                    continue  # la misma etiqueta se leyó también identificada
                add('skip', note=(
                    'Leído el %s en %s sin identificar el producto%s. No se carga: identifícalo en el recuento.'
                    % (read_on, site_label, ' (el nº de serie está en Sage)' if in_sage else '')), **base)
                continue
            if in_sage:
                add('skip', company_code=False, note=(
                    'Leído el %s en %s, pero Sage tiene ese nº de serie con otro producto, con cantidad cero o '
                    'ya casado con otra lectura. Revisar: no se carga.' % (read_on, site_label)), **base)
                continue
            problem = tracked_problem(group['product_id'])
            if problem:
                add('skip', note=problem, **base)
                continue
            move = self._plan_latest_move(ctx, keys, group['first_at'].date())
            if move and move['type'] == 'sale':
                add('skip', company_code='01', sage_move_id=move['id'], note=(
                    'Leído el %s en %s (no está en Sage) y después vendido en Sage: %s. No entra.'
                    % (read_on, site_label, self._plan_move_label(move))), **base)
                continue
            if move and move['type'] == 'deposit':
                add('deposit', company_code=move['code'] or '01', sage_move_id=move['id'], note=(
                    'Leído el %s en %s y después dejado en depósito en Sage: %s. Entra en el depósito de ese cliente.'
                    % (read_on, site_label, self._plan_move_label(move))),
                    **dict(base, **deposit_vals(None, move['partner_name'], keys, date=move['date'])))
                continue
            location = self._plan_location(ctx, '01', group['site'])
            if not location:
                add('skip', company_code='01', note=(
                    'Alta leída el %s en una ubicación que no es de ninguna nave de RMS. No se carga.' % read_on), **base)
                continue
            add('alta', company_code='01', location_id=location, note=(
                'Leído el %s en %s y no está en Sage: entra a nombre de RMS como «Alta por revisar». Coste pendiente.'
                % (read_on, site_label)), **base)

    def _plan_quantities(self, ctx, lines):
        """Productos sin nº de serie. En las naves contadas manda lo contado (la
        nave entera, las 3 empresas juntas): se reparte entre empresas hasta lo
        que Sage dice de cada una (RMS, Espacio, RJB); el sobrante a RMS y lo
        que falta, al fantasma de la empresa a la que le falta."""
        tracking, counted_sites, states = ctx['tracking'], ctx['counted_sites'], ctx['states']
        load_date = self.date
        sage = defaultdict(lambda: {'qty': 0.0, 'value': 0.0, 'line_id': False, 'article': '', 'state': 'nuevo',
                                    'warehouse_code': ''})
        deposits = defaultdict(lambda: {'qty': 0.0, 'value': 0.0, 'line_id': False, 'article': '', 'state': 'nuevo'})
        deposit_by_wh = defaultdict(float)
        stock_rows = []
        for row in ctx['sage_rows']:
            if row['sn'] not in ('', 'SN') or row['quantity'] <= 0:
                continue
            if row['stock_kind'] == 'deposit':
                if not row['product_id']:
                    lines.append({'kind': 'skip', 'sage_company_code': row['code'], 'company_id': ctx['company_by_code'].get(row['code']),
                                  'site_number': 0, 'article_code': row['article'], 'quantity': row['quantity'],
                                  'sage_qty': row['quantity'], 'sage_line_id': row['id'], 'sage_partner_name': row['partner_name'],
                                  'note': 'Depósito por cantidad de un artículo de Sage sin producto en Odoo (%s). No se carga.' % row['article']})
                    continue
                entry = deposits[(row['code'], (row['partner_name'] or '').strip(), row['product_id'])]
                entry['qty'] += row['quantity']
                entry['value'] += row['quantity'] * row['cost']
                entry.update(line_id=entry['line_id'] or row['id'], article=row['article'], state=row['state'])
                deposit_by_wh[(row['code'], row['warehouse_id'], row['product_id'])] += row['quantity']
            elif not row['in_deposit']:
                stock_rows.append(row)
        for row in stock_rows:
            quantity = row['quantity']
            # La valoración de Sage incluye lo que está en depósito: se descuenta
            # del mismo almacén para no cargarlo dos veces.
            key = (row['code'], row['warehouse_id'], row['product_id'])
            if row['product_id'] and deposit_by_wh.get(key):
                taken = min(quantity, deposit_by_wh[key])
                deposit_by_wh[key] -= taken
                quantity -= taken
                if quantity <= 0:
                    continue
            site = ctx['wh_site'].get(row['warehouse_id'], 0)
            if not row['product_id'] or not site:
                lines.append({
                    'kind': 'skip', 'sage_company_code': row['code'], 'company_id': ctx['company_by_code'].get(row['code']),
                    'site_number': site, 'product_id': row['product_id'] or False, 'article_code': row['article'],
                    'quantity': quantity, 'sage_qty': quantity, 'sage_line_id': row['id'], 'sage_cost': row['cost'],
                    'sage_warehouse_code': row['warehouse_code'], 'sage_state': row['state'],
                    'note': ('El artículo de Sage %s no tiene producto en Odoo. No se carga.' % row['article'])
                    if not row['product_id'] else
                    ('Almacén de Sage sin nave (%s): sin ubicar, no cargado.' % row['warehouse_code'])})
                continue
            entry = sage[(site, row['product_id'], row['code'])]
            entry['qty'] += quantity
            entry['value'] += quantity * row['cost']
            entry.update(line_id=entry['line_id'] or row['id'], article=row['article'], state=row['state'],
                         warehouse_code=row['warehouse_code'])

        counted = defaultdict(lambda: {'qty': 0.0, 'scan_id': False, 'session_id': False, 'at': False})
        for scan in ctx['scan_rows']:
            if scan['scan_type'] != 'product' or not scan['product_id']:
                continue
            entry = counted[(scan['site'], scan['product_id'])]
            entry['qty'] += scan['quantity'] or 0.0
            entry.update(scan_id=scan['id'], session_id=scan['session_id'], at=scan['scanned_at'])

        def line(kind, code, site, product_id, quantity, note, entry=None, count=None, unverified=False, sage_qty=0.0):
            vals = {
                'kind': kind, 'sage_company_code': code, 'company_id': ctx['company_by_code'].get(code),
                'site_number': site, 'product_id': product_id, 'quantity': quantity, 'note': note,
                'unverified': unverified, 'sage_qty': sage_qty,
                'location_id': self._plan_location(ctx, code, site) if kind in ('qty_counted', 'qty_sage') else False,
            }
            if entry:
                vals.update(sage_line_id=entry['line_id'], article_code=entry['article'], sage_state=entry['state'],
                            sage_warehouse_code=entry.get('warehouse_code'),
                            sage_cost=entry['value'] / entry['qty'] if entry['qty'] else 0.0,
                            state_id=False)
            if count:
                vals.update(scan_id=count['scan_id'], session_id=count['session_id'], scanned_at=count['at'],
                            counted_qty=count['qty'])
            if vals['kind'] in ('qty_counted', 'qty_sage') and not vals['location_id']:
                vals.update(kind='skip', unverified=False, note=(
                    'La empresa %s no tiene almacén de Odoo en %s. No se carga. ' % (
                        COMPANY_LABEL.get(code, code), SITE_NAMES.get(site, 'esa nave'))) + note)
            lines.append(vals)

        def problem(product_id):
            kind = tracking.get(product_id)
            if kind in ('serial', 'lot'):
                return 'En Odoo el producto lleva nº de serie y aquí no lo hay: no se puede cargar por cantidad.'
            if kind == 'no_stock':
                return 'El producto no es almacenable en Odoo. No se carga.'
            return ''

        pairs = {(site, product_id) for (site, product_id, _code) in sage} | set(counted)
        for site, product_id in sorted(pairs):
            by_company = {code: sage[(site, product_id, code)] for code in COMPANY_ORDER
                          if (site, product_id, code) in sage}
            count = counted.get((site, product_id))
            site_label = SITE_NAMES.get(site, 'una ubicación sin nave')
            trouble = problem(product_id)
            if trouble:
                for code, entry in by_company.items():
                    line('skip', code, site, product_id, entry['qty'], trouble, entry, count, sage_qty=entry['qty'])
                if count and not by_company:
                    line('skip', '01', site, product_id, count['qty'], trouble, None, count)
                continue
            if site not in counted_sites:
                for code, entry in by_company.items():
                    line('qty_sage', code, site, product_id, entry['qty'],
                         'Nave no contada (%s): entra la cantidad de Sage, sin verificar.' % site_label,
                         entry, None, unverified=True, sage_qty=entry['qty'])
                if count and count['qty'] > 0 and (not site or not by_company):
                    line('skip', '01', site, product_id, count['qty'],
                         'Contado por cantidad en %s, que no está marcada como nave contada. No se carga.' % site_label,
                         None, count)
                continue
            if not count:
                for code, entry in by_company.items():
                    line('qty_sage', code, site, product_id, entry['qty'],
                         'Nadie lo contó en %s: entra la cantidad de Sage, sin verificar.' % site_label,
                         entry, None, unverified=True, sage_qty=entry['qty'])
                continue
            remaining = count['qty']
            total_sage = sum(entry['qty'] for entry in by_company.values())
            for code in COMPANY_ORDER:
                entry = by_company.get(code)
                if not entry:
                    continue
                take = min(remaining, entry['qty'])
                remaining -= take
                if take > 0:
                    line('qty_counted', code, site, product_id, take,
                         'Contado %s en %s (Sage: %s entre las tres empresas). A %s le corresponden %s.' % (
                             _num(count['qty']), site_label, _num(total_sage), COMPANY_LABEL[code], _num(take)),
                         entry, count, sage_qty=entry['qty'])
                if entry['qty'] - take > 0:
                    line('phantom', code, site, product_id, entry['qty'] - take,
                         'Sage dice %s de %s en %s y solo se contaron %s en total: faltan %s, a «Pendiente de localizar».' % (
                             _num(entry['qty']), COMPANY_LABEL[code], site_label, _num(count['qty']),
                             _num(entry['qty'] - take)),
                         entry, count, sage_qty=entry['qty'])
            if remaining > 0:
                note = ('Sobrante: se contaron %s en %s y Sage dice %s. Las %s de más entran a nombre de RMS.' % (
                    _num(count['qty']), site_label, _num(total_sage), _num(remaining))) if by_company else (
                    'Contado %s en %s y no está en Sage: entra a nombre de RMS. Coste pendiente.' % (
                        _num(count['qty']), site_label))
                line('qty_counted', '01', site, product_id, remaining, note, by_company.get('01'), count,
                     sage_qty=by_company['01']['qty'] if '01' in by_company else 0.0)

        # Depósitos por cantidad (sin nº de serie): según Sage, sin verificar.
        for (code, partner_name, product_id), entry in sorted(deposits.items(), key=lambda item: (item[0][0], item[0][1], item[0][2])):
            trouble = problem(product_id)
            partner_id, _matched = self._plan_partner(ctx, partner_name)
            vals = {
                'kind': 'skip' if trouble else 'deposit', 'sage_company_code': code,
                'company_id': ctx['company_by_code'].get(code), 'site_number': 0, 'product_id': product_id,
                'quantity': entry['qty'], 'sage_qty': entry['qty'], 'sage_line_id': entry['line_id'],
                'article_code': entry['article'], 'sage_state': entry['state'],
                'sage_cost': entry['value'] / entry['qty'] if entry['qty'] else 0.0,
                'partner_id': partner_id, 'sage_partner_name': partner_name or '(sin nombre en Sage)',
                'deposit_date': load_date, 'unverified': not trouble,
                'note': trouble or ('Sage tiene %s en depósito en %s. Entra en el depósito de ese cliente, sin verificar.'
                                    % (_num(entry['qty']), partner_name or 'un cliente sin nombre')),
            }
            lines.append(vals)
        # Estado de los artículos por cantidad: no llevan nº de serie, no se guarda estado.
        for vals in lines:
            vals.setdefault('state_id', False)
        _ = states


def _num(value):
    return ('%.3f' % (value or 0.0)).rstrip('0').rstrip('.')
