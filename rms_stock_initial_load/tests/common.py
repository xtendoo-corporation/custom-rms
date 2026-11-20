# -*- coding: utf-8 -*-
"""Datos comunes: 3 empresas con sus almacenes RMSn / ETn / RJBn enlazados a
los almacenes de Sage, un recuento en Sevilla (nave 7) y ayudas para crear
existencias de Sage, lecturas y movimientos de Sage."""
import itertools
from datetime import date, datetime

from odoo.tests import TransactionCase

COUNT_DAY = datetime(2026, 11, 10, 10, 0, 0)
AFTER = date(2026, 11, 15)
BEFORE = date(2026, 11, 2)


class LoadCommon(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.c1 = env.company
        cls.c2 = env['res.company'].create({'name': 'Espacio (prueba de carga)'})
        cls.c3 = env['res.company'].create({'name': 'RJB (prueba de carga)'})
        env.user.company_ids |= cls.c2 | cls.c3
        env.user.group_ids |= env.ref('stock.group_stock_manager')
        cls.env = env = env(context=dict(env.context, allowed_company_ids=[cls.c1.id, cls.c2.id, cls.c3.id]))
        cls.wh = {}
        for company, codes in ((cls.c1, ('RMS1', 'RMS6', 'RMS7')), (cls.c2, ('ET7', 'ET6', 'ET1')),
                               (cls.c3, ('RJB7',))):
            for code in codes:
                cls.wh[code] = cls._warehouse(company, code)
        env['rms.sage.warehouse']._setup_default_links()
        SageWh = env['rms.sage.warehouse']
        if not SageWh.search([('sage_company_code', '=', '01'), ('code', '=', 'AL8')]):
            SageWh.create({'sage_company_code': '01', 'code': 'AL8', 'name': 'RA Meyer', 'company_id': cls.c1.id})
        cls.companies = {'01': cls.c1, '02': cls.c2, '03': cls.c3}
        cls.brand = env['product.category'].create({'name': 'LOADTEST Marca'})
        cls.product = cls._product('LOADTEST ALTAVOZ', 'LT-ALT', 'serial')
        cls.product2 = cls._product('LOADTEST MESA', 'LT-MESA', 'serial')
        cls.cable = cls._product('LOADTEST CABLE', 'LT-CABLE', 'none')
        cls.cable2 = cls._product('LOADTEST FUNDA', 'LT-FUNDA', 'none')
        cls.cable3 = cls._product('LOADTEST HIERRO', 'LT-HIERRO', 'none')
        cls.states = {state.code: state for state in env['product.state'].search([])}
        cls.snapshots = {}
        for code in ('01', '02', '03'):
            for kind in ('stock', 'deposit'):
                cls._snapshot(code, kind)
        cls._keys = itertools.count(1)
        cls.session = env['rms.stock.count.session'].create({'location_id': cls.wh['RMS7'].lot_stock_id.id})
        Operator = env['rms.stock.count.operator']
        cls.operator = Operator.browse(Operator.scanner_join(cls.session.id, 'Carga')['operator']['id'])
        cls.session.date_start = COUNT_DAY
        cls.Load = env['rms.initial.load']

    # ------------------------------------------------------------------ ayudas
    @classmethod
    def _warehouse(cls, company, code):
        Warehouse = cls.env['stock.warehouse'].with_context(active_test=False)
        warehouse = Warehouse.search([('code', '=', code)], limit=1)
        if warehouse:
            return warehouse
        known = ('RMS', 'ET', 'RJB')
        free = Warehouse.search([('company_id', '=', company.id)]).filtered(
            lambda w: not (w.code or '').startswith(known))[:1]
        if free:
            free.write({'name': code, 'code': code})
            return free
        return Warehouse.with_company(company).create({'name': code, 'code': code, 'company_id': company.id})

    @classmethod
    def _product(cls, name, ref, tracking, cost=0.0):
        return cls.env['product.product'].create({
            'name': name, 'default_code': ref, 'categ_id': cls.brand.id, 'is_storable': True,
            'tracking': tracking, 'standard_price': cost})

    @classmethod
    def _snapshot(cls, code, kind):
        key = (code, kind)
        if key not in cls.snapshots:
            cls.snapshots[key] = cls.env['rms.sage.snapshot'].create({
                'name': 'Sage %s %s' % key, 'brand_categ_id': cls.brand.id, 'sage_company_code': code,
                'company_id': cls.companies[code].id, 'state': 'current', 'stock_kind': kind})
        return cls.snapshots[key]

    @classmethod
    def sage(cls, code, product, serial, wh='A.7', state='nuevo', qty=1.0, kind='stock', partner=None,
             in_deposit=False, cost=0.0):
        article = (product.default_code if product else 'SIN-PRODUCTO')
        article = {'nuevo': '', 'demo': 'D-', '2mano': '2M-'}[state] + article
        warehouse = cls.env['rms.sage.warehouse'].search(
            [('sage_company_code', '=', code), ('code', '=', wh)], limit=1)
        return cls.env['rms.sage.stock.line'].create({
            'snapshot_id': cls._snapshot(code, kind).id, 'is_current': True, 'warehouse_code': wh,
            'sage_warehouse_id': (warehouse.alias_of_id or warehouse).id, 'article_code': article,
            'article_name': product.name if product else 'Sin producto', 'model_code': article,
            'serial': serial or False, 'quantity': qty, 'product_id': product.id if product else False,
            'state': state, 'match_state': 'ok' if product else 'sin_producto', 'partner_name': partner,
            'in_deposit': in_deposit, 'cost': cost})

    @classmethod
    def sage_deposit(cls, code, product, serial, partner, wh='A.7', state='nuevo'):
        """Sage cuenta el depósito en existencias (marcado) y en depósitos de venta."""
        cls.sage(code, product, serial, wh=wh, state=state, in_deposit=True)
        return cls.sage(code, product, serial, wh=wh, state=state, kind='deposit', partner=partner)

    @classmethod
    def scan(cls, serial, product=None, state=None, at=COUNT_DAY, session=None, scan_type='serial', qty=1.0):
        session = session or cls.session
        operator = cls.operator if session == cls.session else session.operator_ids[:1]
        return cls.env['rms.stock.count.scan'].create({
            'session_id': session.id, 'operator_id': operator.id, 'code': serial, 'raw_code': serial,
            'scan_type': scan_type, 'product_id': product.id if product else False,
            'lot_name': serial if scan_type == 'serial' else False,
            'product_state_id': cls.states[state].id if state else False,
            'quantity': qty, 'scanned_at': at})

    @classmethod
    def count_qty(cls, product, qty, session=None):
        return cls.scan(product.default_code, product, scan_type='product', qty=qty, session=session)

    @classmethod
    def sage_move(cls, serial, move_type, move_date=AFTER, partner=None, wh_from=None, wh_to=None, code='01'):
        return cls.env['rms.sage.serial.move'].create({
            'sage_key': 'LOADTEST-%d' % next(cls._keys), 'move_type': move_type, 'move_date': move_date,
            'serial': serial, 'partner_name': partner, 'warehouse_from': wh_from, 'warehouse_to': wh_to,
            'sage_company_code': code, 'document': 'DOC-%s' % serial})

    def new_load(self, sites=(7,), prepare=True):
        vals = {'name': 'Carga de prueba'}
        vals.update({'site_%d' % site: True for site in sites})
        load = self.Load.create(vals)
        if prepare:
            load.action_prepare()
        return load

    def line(self, load, serial=None, product=None, **filters):
        domain = [('load_id', '=', load.id)]
        if serial:
            domain.append(('lot_name', '=', serial))
        if product:
            domain.append(('product_id', '=', product.id))
        domain += [(key, '=', value) for key, value in filters.items()]
        return self.env['rms.initial.load.line'].search(domain)

    def stock(self, product, location=None, lot=None, companies=None):
        domain = [('product_id', '=', product.id), ('quantity', '!=', 0),
                  '|', ('location_id.usage', 'in', ('internal', 'transit')), ('location_id.rms_phantom', '=', True)]
        if location:
            domain.append(('location_id', '=', location.id))
        if lot:
            domain.append(('lot_id.name', '=', lot))
        return sum(self.env['stock.quant'].sudo().search(domain).mapped('quantity'))

    def lot(self, serial, product=None):
        return self.env['stock.lot'].search([('name', '=', serial), ('product_id', '=', (product or self.product).id)])
