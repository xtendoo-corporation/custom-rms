# -*- coding: utf-8 -*-
"""Caso 3: checklist global de Sage. Un nº de serie que aún no existe en
Odoo se identifica por lo que dice la carpeta de Sage."""

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSageGlobalChecklist(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        warehouse = cls.env['stock.warehouse'].search([('company_id', '=', cls.env.company.id)], limit=1)
        cls.session = cls.env['rms.stock.count.session'].create({'location_id': warehouse.lot_stock_id.id})
        Operator = cls.env['rms.stock.count.operator']
        cls.operator = Operator.browse(Operator.scanner_join(cls.session.id, 'Global')['operator']['id'])
        cls.Scan = cls.env['rms.stock.count.scan']
        cls.brand = cls.env['product.category'].create({'name': 'RMSTEST Global Brand'})
        Product = cls.env['product.product']
        cls.galaxy = Product.create({'name': 'GLOBAL GALAXY', 'categ_id': cls.brand.id,
                                     'is_storable': True, 'tracking': 'serial'})
        cls.leopard = Product.create({'name': 'GLOBAL LEOPARD', 'categ_id': cls.brand.id,
                                      'is_storable': True, 'tracking': 'serial'})
        cls.cable = Product.create({'name': 'GLOBAL CABLE', 'categ_id': cls.brand.id,
                                    'is_storable': True, 'tracking': 'none'})
        cls.snapshot = cls.env['rms.sage.snapshot'].create({
            'name': 'Global test', 'brand_categ_id': cls.brand.id, 'sage_company_code': '02',
        })

    def _sage(self, serial, product=False, article='GLOBAL-ART', warehouse='A.7', state='nuevo'):
        return self.env['rms.sage.stock.line'].create({
            'snapshot_id': self.snapshot.id, 'is_current': True, 'warehouse_code': warehouse,
            'article_code': article, 'model_code': article, 'serial': serial,
            'product_id': product.id if product else False, 'state': state,
            'match_state': 'ok' if product else 'sin_producto',
        })

    def _scan(self, code):
        return self.Scan.scanner_register(self.operator.id, code)

    def test_serial_only_in_sage_takes_its_product(self):
        self._sage('GLX-0001', self.galaxy)
        self.operator.current_product_id = False
        result = self._scan('GLX-0001')
        scan = self.Scan.browse(result['scan']['id'])
        self.assertEqual(scan.scan_type, 'serial')
        self.assertEqual(scan.product_id, self.galaxy)
        self.assertEqual(scan.lot_name, 'GLX-0001')
        self.assertTrue(scan.is_new_lot)
        self.assertIn('según Sage', scan.message)

    def test_normalized_match(self):
        self._sage('0011650', self.galaxy)
        self.operator.current_product_id = False
        scan = self.Scan.browse(self._scan(' 0011650 ')['scan']['id'])
        self.assertEqual(scan.product_id, self.galaxy)

    def test_serial_in_several_products_needs_product(self):
        self._sage('DUP-1', self.galaxy)
        self._sage('DUP-1', self.leopard, article='GLOBAL-ART2')
        self.operator.current_product_id = False
        scan = self.Scan.browse(self._scan('DUP-1')['scan']['id'])
        self.assertEqual(scan.scan_type, 'unknown')
        self.assertIn('varios productos', scan.message)

    def test_current_product_resolves_ambiguity(self):
        self._sage('DUP-2', self.galaxy)
        self._sage('DUP-2', self.leopard, article='GLOBAL-ART2')
        self.operator.current_product_id = self.leopard
        scan = self.Scan.browse(self._scan('DUP-2')['scan']['id'])
        self.assertEqual(scan.scan_type, 'serial')
        self.assertEqual(scan.product_id, self.leopard)

    def test_sage_article_without_product(self):
        self._sage('NOPROD-1', False, article='GLOBAL-UNKNOWN-ART')
        self.operator.current_product_id = False
        scan = self.Scan.browse(self._scan('NOPROD-1')['scan']['id'])
        self.assertEqual(scan.scan_type, 'unknown')
        self.assertIn('GLOBAL-UNKNOWN-ART', scan.message)
        self.assertIn('Artículos sin producto', scan.message)

    def test_untracked_product_is_flagged(self):
        self._sage('CABLE-1', self.cable)
        self.operator.current_product_id = False
        scan = self.Scan.browse(self._scan('CABLE-1')['scan']['id'])
        self.assertEqual(scan.scan_type, 'unknown')
        self.assertIn('no se sigue por nº de serie', scan.message)

    def test_serial_not_in_sage_stays_unknown(self):
        self.operator.current_product_id = False
        scan = self.Scan.browse(self._scan('NOT-IN-SAGE-9')['scan']['id'])
        self.assertEqual(scan.scan_type, 'unknown')

    def test_global_verdict_green_anywhere_with_details(self):
        self._sage('VER-1', self.galaxy, article='0907600102', warehouse='AL1', state='2mano')
        verdict = self.Scan._sage_verdict(['VER-1'], self.session, self.galaxy, ['second_hand'])[0]
        self.assertEqual(verdict['v'], 'ok')
        self.assertEqual(verdict['h'][0][0], '02')       # empresa Sage
        self.assertEqual(verdict['h'][0][1], 'AL1')      # almacén
        self.assertEqual(verdict['h'][0][3], '2Mano')    # estado Sage
        self.assertEqual(verdict['h'][0][4], '0907600102')  # modelo

    def test_global_verdict_state_mismatch_is_amber(self):
        self._sage('VER-2', self.galaxy, state='demo')
        verdict = self.Scan._sage_verdict(['VER-2'], self.session, self.galaxy, ['new'])[0]
        self.assertEqual(verdict['v'], 'est')
        self.assertEqual(verdict['st'], 'Nuevo')
        exdemo = self.Scan._sage_verdict(['VER-2'], self.session, self.galaxy, ['ex_demo'])[0]
        self.assertEqual(exdemo['v'], 'est')  # Ex-Demo no existe en Sage

    def test_global_verdict_duplicate_and_absent(self):
        self._sage('VER-3', self.galaxy, warehouse='AL1')
        self._sage('VER-3', self.galaxy, warehouse='A.7')
        verdicts = self.Scan._sage_verdict(['VER-3', 'NOPE-3'], self.session, [self.galaxy.id, False], ['new', 'new'])
        self.assertEqual([v['v'] for v in verdicts], ['dup', 'none'])

    def test_scan_payload_carries_global_verdict(self):
        self._sage('VER-4', self.galaxy)
        self.operator.current_product_id = False
        result = self._scan('VER-4')
        self.assertEqual(result['sage']['v'], 'ok')

    def test_rescan_with_corrected_state_updates_reading(self):
        self._sage('FIX-1', self.galaxy, state='2mano')
        self.operator.current_product_id = False
        new = self.env.ref('rms_product_state.state_new')
        used = self.env.ref('rms_product_state.state_second_hand')
        self.operator.scanner_set_state(new.id)
        first = self._scan('FIX-1')
        self.assertEqual(first['sage']['v'], 'est')
        self.operator.scanner_set_state(used.id)
        second = self._scan('FIX-1')
        self.assertEqual(second['status'], 'ok')
        self.assertEqual(second['scan']['id'], first['scan']['id'])
        self.assertEqual(self.Scan.browse(first['scan']['id']).product_state_id, used)
        self.assertEqual(second['sage']['v'], 'ok')
        third = self._scan('FIX-1')
        self.assertEqual(third['status'], 'duplicate')

    def test_replaced_snapshot_lines_are_ignored(self):
        line = self._sage('OLD-1', self.galaxy)
        line.is_current = False
        self.operator.current_product_id = False
        scan = self.Scan.browse(self._scan('OLD-1')['scan']['id'])
        self.assertEqual(scan.scan_type, 'unknown')
