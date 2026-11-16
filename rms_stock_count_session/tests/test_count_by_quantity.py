# -*- coding: utf-8 -*-
"""Artículos sin nº de serie: botón "Por cantidad" del escáner y su cotejo
con Sage por nave (rms.sage.checklist.qty)."""

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCountByQuantity(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.c1 = cls.env.company
        cls.c2 = cls.env['res.company'].create({'name': 'Espacio QTY TEST'})
        cls.c3 = cls.env['res.company'].create({'name': 'RJB QTY TEST'})
        cls.env.user.company_ids |= cls.c2 | cls.c3
        Warehouse = cls.env['stock.warehouse']
        cls.wh = {}
        for company, code in ((cls.c1, 'RMS7'), (cls.c2, 'ET7'), (cls.c3, 'RJB7'), (cls.c1, 'RMS1')):
            cls.wh[code] = Warehouse.with_company(company).create(
                {'name': 'QTY %s' % code, 'code': code, 'company_id': company.id})
        cls.brand = cls.env['product.category'].create({'name': 'RMSTEST Qty Brand'})
        Product = cls.env['product.product']

        def product(name, ref, tracking='none'):
            return Product.create({'name': name, 'default_code': ref, 'categ_id': cls.brand.id,
                                   'is_storable': True, 'tracking': tracking})

        cls.cable = product('QTYT CABLE XLR 5M', 'QTYT-XLR5')
        cls.funda = product('QTYT FUNDA ALTAVOZ', 'QTYT-FUNDA')
        cls.hierro = product('QTYT HIERRO VOLADO', 'QTYT-HIERRO')
        cls.grillete = product('QTYT GRILLETE', 'QTYT-GRI')
        cls.odoo_only = product('QTYT BRIDA SOLO ODOO', 'QTYT-BRIDA')
        cls.serial_product = product('QTYT MESA CON SERIE', 'QTYT-MESA', tracking='serial')
        Snapshot = cls.env['rms.sage.snapshot']
        cls.snap = {code: Snapshot.with_company(company).create({
            'name': 'Qty %s' % code, 'brand_categ_id': cls.brand.id, 'sage_company_code': code,
            'company_id': company.id}) for code, company in (('01', cls.c1), ('02', cls.c2), ('03', cls.c3))}
        line = cls._line
        line('01', cls.cable, 30)
        line('02', cls.cable, 10)
        line('01', cls.cable, 7, warehouse='AL1')            # Madrid: otra nave
        line('01', cls.funda, 5)
        line('03', cls.funda, 5, state='demo', article='D-QTYT-FUNDA')
        line('01', cls.hierro, 4)
        line('01', cls.grillete, 100)
        line('01', cls.grillete, 20, deposit=True)            # en depósito: no está en la nave
        line('01', cls.serial_product, 2)                     # sin serie en Sage, con serie en Odoo
        line('01', cls.serial_product, 1, serial='QTYT-SER-1')
        line('02', False, 9, article='QTYT-SINPROD', name='QTYT ADAPTADOR SIN PRODUCTO')
        line('01', cls.hierro, 3, warehouse='A.4')            # almacén dudoso, sin nave
        cls.env['rms.sage.warehouse']._setup_default_links()
        cls.Session = cls.env['rms.stock.count.session']
        cls.Operator = cls.env['rms.stock.count.operator']
        cls.Scan = cls.env['rms.stock.count.scan']
        cls.Qty = cls.env['rms.sage.checklist.qty']
        cls.session = cls.Session.create({'location_id': cls.wh['RMS7'].lot_stock_id.id})
        cls.operator = cls._join(cls.session, 'Ana')
        cls.states = {state['code']: state['id'] for state in cls.operator.scanner_state()['product_states']}

    @classmethod
    def _line(cls, code, product, quantity, warehouse='A.7', state='nuevo', serial=False, deposit=False,
              article=False, name=False):
        return cls.env['rms.sage.stock.line'].sudo().create({
            'snapshot_id': cls.snap[code].id, 'is_current': True, 'warehouse_code': warehouse,
            'article_code': article or product.default_code, 'model_code': article or product.default_code,
            'article_name': name or (product.name if product else False),
            'serial': serial, 'quantity': quantity, 'product_id': product.id if product else False,
            'state': state, 'match_state': 'ok' if product else 'sin_producto', 'in_deposit': deposit})

    @classmethod
    def _join(cls, session, name):
        return cls.Operator.browse(cls.Operator.scanner_join(session.id, name)['operator']['id'])

    def _count(self, product, quantity, operator=None, state='new', mode=False):
        return (operator or self.operator).scanner_qty_count(product.id, quantity, self.states[state], mode)

    def _row(self, product, site=7):
        self.env.flush_all()
        self.Qty.invalidate_model()
        return self.Qty.search([('product_id', '=', product.id), ('site_number', '=', site)])

    # ------------------------------------------------------------------ búsqueda
    def test_search_lists_site_articles_of_the_three_companies(self):
        found = {row['key']: row for row in self.operator.scanner_qty_search('qtyt')}
        # Sevilla: RMS + Espacio + RJB juntas, un artículo por producto.
        for product in (self.cable, self.funda, self.hierro, self.grillete):
            self.assertIn('p%d' % product.id, found)
            self.assertTrue(found['p%d' % product.id]['in_sage'])
            self.assertTrue(found['p%d' % product.id]['ok'])
        self.assertEqual(len([row for row in found.values() if row['product_id'] == self.funda.id]), 1)
        # Producto de Odoo sin seguimiento que Sage no tiene: también se ofrece.
        self.assertFalse(found['p%d' % self.odoo_only.id]['in_sage'])
        # Con nº de serie en Odoo: no se ofrece por cantidad.
        self.assertNotIn('p%d' % self.serial_product.id, found)
        # Artículo de Sage sin producto: se ve, pero no se puede contar.
        missing = found['a:QTYT-SINPROD']
        self.assertFalse(missing['ok'])
        self.assertFalse(missing['product_id'])
        self.assertEqual(missing['name'], 'QTYT ADAPTADOR SIN PRODUCTO')
        # A ciegas: ninguna cantidad de Sage en la respuesta.
        self.assertEqual(set(found['p%d' % self.cable.id]),
                         {'key', 'product_id', 'name', 'ref', 'sage_name', 'article', 'in_sage', 'ok', 'counted'})
        self.assertEqual(found['p%d' % self.cable.id]['counted'], 0)

    def test_search_by_words_and_without_query(self):
        keys = [row['key'] for row in self.operator.scanner_qty_search('xlr cable')]
        self.assertEqual(keys, ['p%d' % self.cable.id])
        self.assertEqual([row['key'] for row in self.operator.scanner_qty_search('QTYT-GRI')],
                         ['p%d' % self.grillete.id])
        # Sin escribir nada: solo lo de Sage de la nave (no todo el catálogo de Odoo).
        keys = {row['key'] for row in self.operator.scanner_qty_search('')}
        self.assertIn('p%d' % self.cable.id, keys)
        self.assertNotIn('p%d' % self.odoo_only.id, keys)

    def test_search_other_site_does_not_mix(self):
        madrid = self._join(self.Session.create({'location_id': self.wh['RMS1'].lot_stock_id.id}), 'Madrid')
        keys = {row['key'] for row in madrid.scanner_qty_search('')}
        self.assertEqual(keys, {'p%d' % self.cable.id})

    # ------------------------------------------------------------------ apuntar
    def test_count_saves_one_reading_with_quantity(self):
        self.operator.current_product_id = self.serial_product
        result = self._count(self.cable, 38)
        self.assertEqual(result['status'], 'ok')
        scan = self.Scan.browse(result['scan']['id'])
        self.assertEqual((scan.scan_type, scan.product_id, scan.quantity), ('product', self.cable, 38))
        self.assertEqual(scan.product_state_id.code, 'new')
        self.assertEqual(scan.location_id, self.wh['RMS7'].lot_stock_id)
        self.assertEqual(result['scan']['quantity'], 38)
        self.assertEqual(result['total'], 38)
        # El producto actual (para los nº de serie nuevos) no cambia.
        self.assertEqual(self.operator.current_product_id, self.serial_product)
        self.assertEqual(self.operator.scanner_qty_search('xlr')[0]['counted'], 38)

    def test_count_again_asks_then_adds_or_replaces(self):
        first = self._count(self.cable, 12)
        ask = self._count(self.cable, 38)
        self.assertEqual(ask['status'], 'confirm')
        self.assertEqual(ask['existing'], 12)
        self.assertEqual(ask['by'], 'Ana')
        self.assertEqual(len(self.operator._qty_scans(self.cable, self.env['product.state'].browse(self.states['new']))), 1)
        added = self._count(self.cable, 38, mode='add')
        self.assertEqual((added['status'], added['total'], added['deleted_ids']), ('ok', 50, []))
        # Otro estado es otra cuenta: no pregunta.
        self.assertEqual(self._count(self.cable, 3, state='demo')['status'], 'ok')
        replaced = self._count(self.cable, 20, mode='replace')
        self.assertEqual(replaced['total'], 20)
        self.assertEqual(set(replaced['deleted_ids']), {first['scan']['id'], added['scan']['id']})
        self.assertFalse(self.Scan.browse(replaced['deleted_ids']).exists())
        scans = self.Scan.search([('session_id', '=', self.session.id), ('product_id', '=', self.cable.id)])
        self.assertEqual(sorted(scans.mapped('quantity')), [3, 20])

    def test_count_asks_when_another_operator_counted_it(self):
        other = self._join(self.session, 'Luis')
        self._count(self.cable, 12, operator=other)
        ask = self._count(self.cable, 38)
        self.assertEqual((ask['status'], ask['existing'], ask['by']), ('confirm', 12, 'Luis'))

    def test_resend_does_not_count_twice(self):
        first = self.operator.scanner_qty_count(self.cable.id, 5, self.states['new'], False, 'uid-qty-1')
        again = self.operator.scanner_qty_count(self.cable.id, 5, self.states['new'], False, 'uid-qty-1')
        self.assertEqual(again['status'], 'resent')
        self.assertEqual(again['scan']['id'], first['scan']['id'])
        self.assertEqual(again['total'], 5)

    def test_correct_and_delete_reading(self):
        scan = self.Scan.browse(self._count(self.cable, 38)['scan']['id'])
        payload = scan.scanner_set_quantity(41)
        self.assertEqual((payload['quantity'], scan.quantity), (41, 41))
        self.assertIn('41', scan.message)
        with self.assertRaises(UserError):
            scan.scanner_set_quantity(0)
        scan.scanner_delete()
        self.assertFalse(scan.exists())
        self.assertEqual(self._count(self.cable, 2)['status'], 'ok')   # ya no pregunta

    def test_only_quantity_readings_can_change_quantity(self):
        self.operator.current_product_id = self.serial_product
        result = self.Scan.scanner_register(self.operator.id, 'QTYT-SER-1')
        with self.assertRaises(UserError):
            self.Scan.browse(result['scan']['id']).scanner_set_quantity(5)

    def test_rejects_missing_product_serial_product_and_bad_quantity(self):
        with self.assertRaisesRegex(UserError, 'Falta crear el producto'):
            self.operator.scanner_qty_count(False, 5, self.states['new'])
        with self.assertRaisesRegex(UserError, 'nº de serie'):
            self._count(self.serial_product, 5)
        for bad in (0, -3, 'abc', 1000000):
            with self.assertRaises(UserError):
                self._count(self.cable, bad)
        self.session.state = 'review'
        with self.assertRaises(UserError):
            self._count(self.cable, 5)

    # ------------------------------------------------------------------ vista
    def test_view_states_without_doubling(self):
        other = self._join(self.session, 'Luis')
        # Cuadra: Sage 30 + 10 (dos empresas); contado 25 + 15 en dos lecturas de dos operarios.
        self._count(self.cable, 25)
        self._count(self.cable, 15, operator=other, mode='add')
        self._count(self.funda, 4)                               # falta: Sage 5 + 5
        self._count(self.funda, 3, state='demo')
        self._count(self.hierro, 6)                              # sobra: Sage 4
        self._count(self.odoo_only, 8)                           # no está en Sage
        cable = self._row(self.cable)
        self.assertEqual(len(cable), 1)
        self.assertEqual((cable.sage_qty, cable.counted_qty, cable.difference, cable.state), (40, 40, 0, 'ok'))
        self.assertEqual(cable.company_breakdown, 'RMS 30 · Espacio 10')
        self.assertEqual((cable.sage_qty_01, cable.sage_qty_02, cable.sage_qty_03), (30, 10, 0))
        self.assertEqual((cable.scan_count, cable.session_count, cable.site_name), (2, 1, 'Sevilla'))
        self.assertEqual(cable.brand_categ_id, self.brand)
        self.assertEqual(cable.default_code, 'QTYT-XLR5')
        funda = self._row(self.funda)
        self.assertEqual((funda.sage_qty, funda.counted_qty, funda.difference, funda.state), (10, 7, -3, 'missing'))
        self.assertEqual(funda.company_breakdown, 'RMS 5 · RJB 5')
        hierro = self._row(self.hierro)
        self.assertEqual((hierro.sage_qty, hierro.counted_qty, hierro.difference, hierro.state), (4, 6, 2, 'extra'))
        # Sin contar; lo que está en depósito no se espera en la nave.
        grillete = self._row(self.grillete)
        self.assertEqual((grillete.sage_qty, grillete.counted_qty, grillete.difference, grillete.state),
                         (100, 0, -100, 'pending'))
        brida = self._row(self.odoo_only)
        self.assertEqual((brida.sage_qty, brida.counted_qty, brida.state), (0, 8, 'not_in_sage'))
        self.assertFalse(brida.company_breakdown)
        self.assertEqual(brida.brand_categ_id, self.brand)
        # Madrid va en su fila: lo contado en Sevilla no la toca.
        madrid = self._row(self.cable, site=1)
        self.assertEqual((madrid.sage_qty, madrid.counted_qty, madrid.state, madrid.site_name),
                         (7, 0, 'pending', 'Madrid'))
        # Almacén dudoso (sin nave): aparte, con la nave vacía.
        doubtful = self._row(self.hierro, site=0)
        self.assertEqual((doubtful.sage_qty, doubtful.state), (3, 'pending'))
        self.assertFalse(doubtful.site_name)
        # Artículo de Sage sin producto y producto con serie en Odoo.
        missing = self.Qty.search([('article_code', '=', 'QTYT-SINPROD')])
        self.assertEqual((missing.sage_qty, missing.state, missing.product_missing, missing.default_code),
                         (9, 'pending', True, 'QTYT-SINPROD'))
        tracked = self._row(self.serial_product)
        self.assertEqual((tracked.sage_qty, tracked.serial_tracked), (2, True))   # la línea con serie no entra
        # Ids únicos y una sola fila por nave + producto.
        rows = self.Qty.search([('brand_categ_id', '=', self.brand.id)])
        self.assertEqual(len(rows), len(set(rows.ids)))
        self.assertEqual(len(rows), 9)

    def test_view_ignores_cancelled_ignored_and_serial_readings(self):
        self._count(self.hierro, 4)
        self.assertEqual(self._row(self.hierro).state, 'ok')
        ignored = self.Scan.browse(self._count(self.funda, 10)['scan']['id'])
        ignored.ignored = True
        self.assertEqual(self._row(self.funda).state, 'pending')
        cancelled = self.Session.create({'location_id': self.wh['RMS7'].lot_stock_id.id})
        self._count(self.grillete, 100, operator=self._join(cancelled, 'Eva'))
        self.assertEqual(self._row(self.grillete).state, 'ok')
        cancelled.state = 'cancel'
        self.assertEqual(self._row(self.grillete).state, 'pending')
        # Una lectura por código de barras (+1) suma como cantidad.
        self.hierro.barcode = 'QTYTBARCODE01'
        self.Scan.scanner_register(self.operator.id, 'QTYTBARCODE01')
        self.assertEqual((self._row(self.hierro).counted_qty, self._row(self.hierro).state), (5, 'extra'))

    def test_view_counts_per_site_of_the_reading(self):
        # Otra empresa cuenta en su almacén de la misma nave (ET7): suma en Sevilla.
        espacio = self._join(self.Session.with_company(self.c2).create(
            {'location_id': self.wh['ET7'].lot_stock_id.id, 'company_id': self.c2.id}), 'Espacio')
        self._count(self.cable, 30)
        self._count(self.cable, 10, operator=espacio)
        madrid = self._join(self.Session.create({'location_id': self.wh['RMS1'].lot_stock_id.id}), 'Madrid')
        self._count(self.cable, 7, operator=madrid)
        sevilla = self._row(self.cable)
        self.assertEqual((sevilla.counted_qty, sevilla.state, sevilla.session_count), (40, 'ok', 2))
        self.assertEqual((self._row(self.cable, site=1).counted_qty, self._row(self.cable, site=1).state), (7, 'ok'))

    # ------------------------------------------------------------------ marcador
    def test_progress_marker_counts_pending_quantity_articles(self):
        progress = self.operator.scanner_progress()
        # cable, funda, hierro, grillete y el artículo sin producto (el de serie en Odoo no).
        self.assertEqual(progress['qty_pending'], 5)
        self.assertEqual(progress['total'], 1)          # los contadores de series no cambian
        self._count(self.cable, 1)
        self._count(self.funda, 10)
        self.assertEqual(self.operator.scanner_progress()['qty_pending'], 3)
        madrid = self._join(self.Session.create({'location_id': self.wh['RMS1'].lot_stock_id.id}), 'Madrid')
        self.assertEqual(madrid.scanner_progress()['qty_pending'], 1)
