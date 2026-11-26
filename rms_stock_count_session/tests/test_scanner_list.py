# -*- coding: utf-8 -*-
"""Vista "Lista" del escáner: lo que Sage dice que hay en la nave (las 3
empresas juntas) por marca > producto > nº de serie, y qué está leído."""

import json

from odoo.tests import TransactionCase, tagged

SAGE_QTY = 7391  # cantidad de Sage inconfundible: nunca debe salir en una respuesta


@tagged('post_install', '-at_install')
class TestScannerList(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.c1 = cls.env.company
        cls.c2 = cls.env['res.company'].create({'name': 'Espacio LISTA TEST'})
        cls.c3 = cls.env['res.company'].create({'name': 'RJB LISTA TEST'})
        cls.env.user.company_ids |= cls.c2 | cls.c3
        Warehouse = cls.env['stock.warehouse']
        cls.wh = {}
        for company, code in ((cls.c1, 'RMS7'), (cls.c2, 'ET7'), (cls.c3, 'RJB7'), (cls.c1, 'RMS1')):
            cls.wh[code] = Warehouse.with_company(company).create(
                {'name': 'LISTA %s' % code, 'code': code, 'company_id': company.id})
        Category = cls.env['product.category']
        cls.atlas = Category.create({'name': 'LISTATEST AtlasIED'})
        cls.meyer = Category.create({'name': 'LISTATEST Meyer'})
        Product = cls.env['product.product']

        def product(name, ref, brand, tracking='serial'):
            return Product.create({'name': name, 'default_code': ref, 'categ_id': brand.id,
                                   'is_storable': True, 'tracking': tracking})

        cls.amp = product('LISTAT AMPLIFICADOR', 'LT-AMP', cls.atlas)
        cls.speaker = product('LISTAT ALTAVOZ TECHO', 'LT-SPK', cls.atlas)
        cls.galaxy = product('LISTAT GALAXY', 'LT-GLX', cls.meyer)
        cls.cable = product('LISTAT CABLE', 'LT-CABLE', cls.atlas, tracking='none')
        cls.funda = product('LISTAT FUNDA', 'LT-FUNDA', cls.meyer, tracking='none')
        Snapshot = cls.env['rms.sage.snapshot']
        companies = {'01': cls.c1, '02': cls.c2, '03': cls.c3}
        cls.snap = {(code, brand.id): Snapshot.with_company(companies[code]).create({
            'name': 'Lista %s %s' % (code, brand.name), 'brand_categ_id': brand.id, 'sage_company_code': code,
            'company_id': companies[code].id}) for code in companies for brand in (cls.atlas, cls.meyer)}
        line = cls._line
        # AtlasIED: 3 amplificadores (uno por empresa, uno con "SN" delante) y 2 altavoces.
        cls.l_amp1 = line('01', cls.amp, 'AMP-0001')
        cls.l_amp2 = line('02', cls.amp, 'SN20002')
        cls.l_amp3 = line('03', cls.amp, 'AMP-0003', state='demo')
        line('01', cls.speaker, 'SPK-0001')
        line('01', cls.speaker, 'SPK-0002')
        # Fuera de la lista: depósito en cliente y otra nave (Madrid).
        line('01', cls.amp, 'AMP-DEPOSITO', deposit=True)
        line('01', cls.amp, 'AMP-MADRID', warehouse='AL1')
        # Meyer: 2 Galaxy.
        line('01', cls.galaxy, 'GLX-0001')
        line('02', cls.galaxy, 'GLX-0002')
        # Por cantidad (sin nº de serie).
        line('01', cls.cable, False, quantity=SAGE_QTY)
        line('02', cls.cable, False, quantity=SAGE_QTY)
        line('01', cls.funda, False, quantity=SAGE_QTY)
        cls.env['rms.sage.warehouse']._setup_default_links()
        cls.Session = cls.env['rms.stock.count.session']
        cls.Operator = cls.env['rms.stock.count.operator']
        cls.Scan = cls.env['rms.stock.count.scan']
        cls.session = cls.Session.create({'location_id': cls.wh['RMS7'].lot_stock_id.id})
        cls.operator = cls._join(cls.session, 'Ana')
        cls.states = {state['code']: state['id'] for state in cls.operator.scanner_state()['product_states']}

    @classmethod
    def _line(cls, code, product, serial, warehouse='A.7', state='nuevo', deposit=False, quantity=1):
        return cls.env['rms.sage.stock.line'].sudo().create({
            'snapshot_id': cls.snap[(code, product.categ_id.id)].id, 'is_current': True,
            'warehouse_code': warehouse, 'article_code': product.default_code, 'model_code': product.default_code,
            'article_name': product.name, 'serial': serial, 'quantity': quantity, 'product_id': product.id,
            'state': state, 'match_state': 'ok', 'in_deposit': deposit})

    @classmethod
    def _join(cls, session, name):
        return cls.Operator.browse(cls.Operator.scanner_join(session.id, name)['operator']['id'])

    def _scan(self, code, operator=None, state='new'):
        operator = operator or self.operator
        return self.Scan.scanner_register(operator.id, code, product_state_id=self.states[state])

    def _brand(self, data, brand):
        return next(b for b in data['brands'] if b['id'] == brand.id)

    def _serials(self, product, brand=None, **kwargs):
        return self.operator.scanner_list_serials((brand or self.atlas).id, 'p%d' % product.id, **kwargs)

    # ------------------------------------------------------------------

    def test_brand_and_product_totals_three_companies(self):
        self._scan('AMP-0001')
        data = self.operator.scanner_list_brands()
        self.assertTrue(data['has_sage'])
        atlas, meyer = self._brand(data, self.atlas), self._brand(data, self.meyer)
        self.assertEqual((atlas['total'], atlas['counted']), (5, 1))     # 3 empresas juntas
        self.assertEqual((meyer['total'], meyer['counted']), (2, 0))
        self.assertEqual((atlas['qty_total'], atlas['qty_counted']), (1, 0))
        # Mismos números que el marcador fijo del escáner.
        progress = self.operator.scanner_progress()
        self.assertEqual((data['total'], data['counted']), (progress['total'], progress['counted']))
        self.assertEqual(data['qty_total'] - data['qty_counted'], progress['qty_pending'])
        products = self.operator.scanner_list_products(self.atlas.id)['products']
        by_key = {p['key']: p for p in products}
        self.assertEqual((by_key['p%d' % self.amp.id]['total'], by_key['p%d' % self.amp.id]['counted']), (3, 1))
        self.assertEqual((by_key['p%d' % self.speaker.id]['total'], by_key['p%d' % self.speaker.id]['counted']), (2, 0))
        self.assertEqual(by_key['p%d' % self.amp.id]['ref'], 'LT-AMP')
        rows = {r['serial']: r for r in self._serials(self.amp)['rows']}
        self.assertEqual(set(rows), {'AMP-0001', 'SN20002', 'AMP-0003'})
        self.assertEqual(rows['AMP-0001']['k'], 'ok')
        self.assertEqual(rows['AMP-0001']['by'], 'Ana')
        self.assertTrue(rows['AMP-0001']['here'])
        self.assertEqual(rows['SN20002']['k'], 'todo')
        self.assertEqual((rows['SN20002']['co'], rows['AMP-0003']['co']), ('Espacio', 'RJB'))
        self.assertEqual(rows['AMP-0003']['st_name'], 'Demo')

    def test_sn_prefix_matches(self):
        # AtlasIED: Sage guarda "SN20002" y la etiqueta trae "20002".
        self._scan('20002')
        rows = {r['serial']: r for r in self._serials(self.amp)['rows']}
        self.assertEqual(rows['SN20002']['k'], 'ok')
        self.assertEqual(self._brand(self.operator.scanner_list_brands(), self.atlas)['counted'], 1)

    def test_read_in_other_session_counts_and_cancelled_does_not(self):
        other = self.Session.create({'location_id': self.wh['RMS7'].lot_stock_id.id})
        pepe = self._join(other, 'Pepe')
        self._scan('SPK-0001', operator=pepe)
        row = {r['serial']: r for r in self._serials(self.speaker)['rows']}['SPK-0001']
        self.assertEqual((row['k'], row['by'], row['sess'], row['here']), ('ok', 'Pepe', other.name, False))
        self.assertEqual(self._brand(self.operator.scanner_list_brands(), self.atlas)['counted'], 1)
        other.state = 'cancel'
        row = {r['serial']: r for r in self._serials(self.speaker)['rows']}['SPK-0001']
        self.assertEqual(row['k'], 'todo')
        self.assertEqual(self._brand(self.operator.scanner_list_brands(), self.atlas)['counted'], 0)

    def test_state_mismatch_is_amber(self):
        self._scan('AMP-0003', state='new')          # Sage dice Demo
        row = {r['serial']: r for r in self._serials(self.amp)['rows']}['AMP-0003']
        self.assertEqual((row['k'], row['st_name'], row['read_state']), ('est', 'Demo', 'Nuevo'))
        atlas = self._brand(self.operator.scanner_list_brands(), self.atlas)
        self.assertEqual((atlas['counted'], atlas['review']), (1, 1))
        # Mismo veredicto que la vista "Lecturas".
        scan = self.Scan.search([('operator_id', '=', self.operator.id)], limit=1)
        self.assertEqual(scan._scanner_payload()['sage']['v'], 'est')
        # Corregido el estado y vuelto a leer: verde.
        self._scan('AMP-0003', state='demo')
        row = {r['serial']: r for r in self._serials(self.amp)['rows']}['AMP-0003']
        self.assertEqual(row['k'], 'ok')

    def test_deposits_and_other_sites_are_out(self):
        serials = [r['serial'] for r in self._serials(self.amp)['rows']]
        self.assertNotIn('AMP-DEPOSITO', serials)
        self.assertNotIn('AMP-MADRID', serials)
        # Leídos aquí tampoco entran en la lista ni en sus contadores (ámbar en "Lecturas").
        self._scan('AMP-MADRID')
        self._scan('AMP-DEPOSITO')
        data = self.operator.scanner_list_brands()
        self.assertEqual((self._brand(data, self.atlas)['total'], self._brand(data, self.atlas)['counted']), (5, 0))
        self.assertEqual(data['extra_count'], 0)        # están en Sage: no son altas

    def test_not_in_sage_goes_to_extra_group(self):
        self.operator.current_product_id = self.amp
        self._scan('ALTA-9001')
        luis = self._join(self.session, 'Luis')
        luis.current_product_id = self.amp
        self._scan('ALTA-9001', operator=luis)          # el mismo equipo, otra persona: una sola alta
        self._scan('AMP-0001')
        data = self.operator.scanner_list_brands()
        self.assertEqual(data['extra_count'], 1)
        extra = self.operator.scanner_list_extra()
        self.assertEqual(extra['total'], 1)
        self.assertEqual(extra['rows'][0]['serial'], 'ALTA-9001')
        self.assertEqual(extra['rows'][0]['ref'], 'LT-AMP')
        self.assertIn('Ana', extra['rows'][0]['by'])
        self.assertIn('Luis', extra['rows'][0]['by'])
        self.assertEqual(self.operator.scanner_progress()['not_in_sage'], 2)   # el marcador cuenta lecturas
        # No se mezclan con lo de Sage ni salen al filtrar "solo lo que falta".
        self.assertEqual(self._brand(data, self.atlas)['total'], 5)
        self.assertEqual(self.operator.scanner_list_brands('pending')['extra_count'], 0)

    def test_filters(self):
        self._scan('AMP-0001')
        self._scan('GLX-0001')
        self._scan('GLX-0002')
        pending = self.operator.scanner_list_brands('pending')
        # Meyer ya no tiene equipos pendientes, pero sí su funda por cantidad.
        meyer = self._brand(pending, self.meyer)
        self.assertEqual((meyer['shown'], meyer['qty_shown']), (0, 1))
        self.assertEqual(self._brand(pending, self.atlas)['total'], 5)       # los totales no cambian con el filtro
        self.assertEqual([r['serial'] for r in self._serials(self.amp, flt='pending')['rows']], ['AMP-0003', 'SN20002'])
        self.assertEqual([r['serial'] for r in self._serials(self.amp, flt='done')['rows']], ['AMP-0001'])
        done = self.operator.scanner_list_brands('done')
        self.assertEqual({b['id'] for b in done['brands']}, {self.atlas.id, self.meyer.id})
        products = self.operator.scanner_list_products(self.atlas.id, 'done')
        self.assertEqual([p['key'] for p in products['products']], ['p%d' % self.amp.id])
        self.assertEqual(products['qty'], [])
        self.assertEqual(self.operator.scanner_list_products(self.meyer.id, 'pending')['products'], [])

    def test_search(self):
        # Por marca.
        data = self.operator.scanner_list_brands('all', 'atlasied')
        self.assertEqual([b['id'] for b in data['brands']], [self.atlas.id])
        # Por referencia y por nombre.
        self.assertEqual([p['ref'] for p in self.operator.scanner_list_products(self.atlas.id, 'all', 'lt-spk')['products']],
                         ['LT-SPK'])
        self.assertEqual([p['ref'] for p in self.operator.scanner_list_products(self.atlas.id, 'all', 'techo')['products']],
                         ['LT-SPK'])
        # Por parte del nº de serie: solo ese equipo, y el servidor abre los grupos.
        auto = self.operator.scanner_list_refresh('all', '0003', auto=True)
        self.assertEqual([b['id'] for b in auto['brands']], [self.atlas.id])
        products = auto['products'][str(self.atlas.id)]['products']
        self.assertEqual([p['key'] for p in products], ['p%d' % self.amp.id])
        serials = auto['serials']['%d|p%d' % (self.atlas.id, self.amp.id)]
        self.assertEqual([r['serial'] for r in serials['rows']], ['AMP-0003'])
        self.assertEqual(self.operator.scanner_list_brands('all', 'no-existe-zz')['brands'], [])
        # Varias palabras: todas tienen que casar.
        self.assertEqual(self.operator.scanner_list_brands('all', 'meyer amplificador')['brands'], [])
        # Caracteres raros no rompen la consulta.
        self.operator.scanner_list_brands('all', "%' _ \\ ; --")

    def test_refresh_only_open_groups(self):
        self._scan('AMP-0001')
        opened = [[self.atlas.id, [['p%d' % self.amp.id, 200]]]]
        data = self.operator.scanner_list_refresh('all', '', opened)
        self.assertEqual(set(data['products']), {str(self.atlas.id)})
        self.assertEqual(set(data['serials']), {'%d|p%d' % (self.atlas.id, self.amp.id)})
        self.assertEqual(len(data['brands']), 2)
        closed = self.operator.scanner_list_refresh('all', '', [])
        self.assertFalse(closed['products'] or closed['serials'])

    def test_by_quantity_never_exposes_sage_quantity(self):
        products = self.operator.scanner_list_products(self.atlas.id)
        self.assertEqual([q['ref'] for q in products['qty']], ['LT-CABLE'])
        item = products['qty'][0]
        self.assertEqual((item['is_counted'], item['counted'], item['ok'], item['product_id']),
                         (False, 0, True, self.cable.id))
        self.operator.scanner_qty_count(self.cable.id, 12, self.states['new'])
        item = self.operator.scanner_list_products(self.atlas.id)['qty'][0]
        self.assertEqual((item['is_counted'], item['counted']), (True, 12))
        atlas = self._brand(self.operator.scanner_list_brands(), self.atlas)
        self.assertEqual((atlas['qty_total'], atlas['qty_counted']), (1, 1))
        # Recuento a ciegas: ninguna respuesta lleva la cantidad de Sage (ni su suma).
        answers = [
            self.operator.scanner_list_brands(), self.operator.scanner_list_brands('pending', 'cable'),
            self.operator.scanner_list_products(self.atlas.id), self.operator.scanner_list_products(self.meyer.id),
            self._serials(self.amp), self.operator.scanner_list_extra(),
            self.operator.scanner_list_refresh('all', 'lt', auto=True),
            self.operator._list_print_data(False, False), self.operator._list_print_data(self.atlas.id, True),
        ]
        text = json.dumps(answers, default=str)
        self.assertNotIn(str(SAGE_QTY), text)
        self.assertNotIn(str(SAGE_QTY * 2), text)
        self.assertNotIn('cost', text)

    def test_by_quantity_with_sage_quantity_enabled(self):
        """Con el parámetro activado: «N de M», el artículo sigue en "lo que
        falta" hasta completarlo y la marca cuenta unidades."""
        self.env['ir.config_parameter'].sudo().set_param('rms_stock_count_session.list_show_sage_qty', '1')
        total = SAGE_QTY * 2                      # LT-CABLE está en dos empresas
        item = self.operator.scanner_list_products(self.atlas.id)['qty'][0]
        self.assertEqual((item['ref'], item['counted'], item['sage_qty']), ('LT-CABLE', 0, total))
        self.operator.scanner_qty_count(self.cable.id, 3, self.states['new'])
        item = self.operator.scanner_list_products(self.atlas.id)['qty'][0]
        self.assertEqual((item['is_counted'], item['counted'], item['sage_qty']), (True, 3, total))
        # A medias: sigue saliendo en "Solo lo que falta" (y también en "Solo leído").
        self.assertEqual([q['ref'] for q in self.operator.scanner_list_products(self.atlas.id, 'pending')['qty']], ['LT-CABLE'])
        self.assertEqual([q['ref'] for q in self.operator.scanner_list_products(self.atlas.id, 'done')['qty']], ['LT-CABLE'])
        atlas = self._brand(self.operator.scanner_list_brands(), self.atlas)
        self.assertEqual((atlas['qty_units'], atlas['qty_units_counted']), (total, 3))
        # Completo: deja de salir en "lo que falta"; lo que sobra no infla el avance.
        self.operator.scanner_qty_count(self.cable.id, total, self.states['new'], 'add')
        self.assertFalse(self.operator.scanner_list_products(self.atlas.id, 'pending')['qty'])
        atlas = self._brand(self.operator.scanner_list_brands(), self.atlas)
        self.assertEqual((atlas['qty_units'], atlas['qty_units_counted']), (total, total))
        # El marcador fijo del escáner no cambia de significado.
        data, progress = self.operator.scanner_list_brands(), self.operator.scanner_progress()
        self.assertEqual(data['qty_total'] - data['qty_counted'], progress['qty_pending'])

    def test_pagination(self):
        for index in range(1, 8):
            self._line('01', self.galaxy, 'PAG-%04d' % index)
        self.env['rms.sage.warehouse']._relink_lines()
        first = self._serials(self.galaxy, brand=self.meyer, limit=4)
        self.assertEqual((first['total'], len(first['rows']), first['offset']), (9, 4, 0))
        second = self._serials(self.galaxy, brand=self.meyer, offset=4, limit=4)
        third = self._serials(self.galaxy, brand=self.meyer, offset=8, limit=4)
        serials = [r['serial'] for r in first['rows'] + second['rows'] + third['rows']]
        self.assertEqual(len(serials), 9)
        self.assertEqual(len(set(serials)), 9)
        self.assertEqual(serials, sorted(serials, key=lambda s: s.replace('-', '')))

    def test_print_list(self):
        self._scan('AMP-0001')
        action = self.operator.scanner_list_print(self.atlas.id, True)
        self.assertEqual(action['tag'], 'rms_print_label')
        self.assertIn('/report/pdf/rms_stock_count_session.report_count_list/%d' % self.operator.id, action['params']['url'])
        pending = self.operator._list_print_data(self.atlas.id, True)
        self.assertEqual([g['name'] for g in pending['groups']], [self.atlas.name])
        serials = [row['serial'] for product in pending['groups'][0]['products'] for row in product['rows']]
        self.assertEqual(sorted(serials), ['AMP-0003', 'SN20002', 'SPK-0001', 'SPK-0002'])
        self.assertEqual([q['ref'] for q in pending['groups'][0]['qty']], ['LT-CABLE'])
        everything = self.operator._list_print_data(False, False)
        self.assertEqual(len(everything['groups']), 2)
        html = self.env['ir.actions.report']._render_qweb_html(
            'rms_stock_count_session.report_count_list', self.operator.ids,
            data={'brand_id': '0', 'only_pending': '0'})[0].decode()
        for expected in ('AMP-0001', 'SN20002', 'GLX-0002', 'LT-CABLE', 'Por cantidad', self.atlas.name):
            self.assertIn(expected, html)
        self.assertNotIn(str(SAGE_QTY), html)
        self.assertNotIn('AMP-DEPOSITO', html)

    def test_inventory_user_can_use_the_list(self):
        user = self.env['res.users'].create({
            'name': 'Lista almacén', 'login': 'lista_almacen_test',
            'group_ids': [(6, 0, [self.env.ref('stock.group_stock_user').id])],
            'company_id': self.c1.id, 'company_ids': [(6, 0, [self.c1.id])]})
        operator = self.operator.with_user(user)
        self._scan('AMP-0001')
        data = operator.scanner_list_brands()
        self.assertEqual(self._brand(data, self.atlas)['total'], 5)       # también lo de Espacio y RJB
        self.assertTrue(operator.scanner_list_products(self.atlas.id)['products'])
        self.assertTrue(operator.scanner_list_serials(self.atlas.id, 'p%d' % self.amp.id)['rows'])
        self.assertEqual(data['total'], operator.scanner_progress()['total'])

    def test_no_sage_site(self):
        session = self.Session.create({'location_id': self.wh['RMS1'].lot_stock_id.id})
        operator = self._join(session, 'Sin Sage')
        # RMS1 solo tiene el equipo de Madrid.
        data = operator.scanner_list_brands()
        self.assertEqual(data['total'], 1)
        self.env['rms.sage.warehouse'].sudo().search([]).write({'location_id': False})
        data = operator.scanner_list_brands()
        self.assertFalse(data['has_sage'])
        self.assertEqual(data['brands'], [])
        self.assertEqual(operator.scanner_list_products(self.atlas.id), {'products': [], 'qty': []})
