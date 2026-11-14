# -*- coding: utf-8 -*-
"""Madrid/Sevilla: almacenes Sage de las 3 empresas enlazados, alias (AL7 = A.7)
y marcador por nave física (las 3 empresas de la misma nave juntas)."""

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSageSites(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.c1 = cls.env.company
        cls.c2 = cls.env['res.company'].create({'name': 'Espacio TEST'})
        cls.c3 = cls.env['res.company'].create({'name': 'RJB TEST'})
        cls.env.user.company_ids |= cls.c2 | cls.c3
        Warehouse = cls.env['stock.warehouse']
        cls.wh = {}
        for company, code in ((cls.c1, 'RMS7'), (cls.c2, 'ET7'), (cls.c3, 'RJB7'), (cls.c1, 'RMS1')):
            cls.wh[code] = Warehouse.with_company(company).create(
                {'name': 'TEST %s' % code, 'code': code, 'company_id': company.id})
        cls.brand = cls.env['product.category'].create({'name': 'RMSTEST Sites Brand'})
        cls.product = cls.env['product.product'].create({'name': 'SITES GALAXY', 'categ_id': cls.brand.id,
                                                         'is_storable': True, 'tracking': 'serial'})
        Snapshot = cls.env['rms.sage.snapshot']
        cls.snap = {code: Snapshot.with_company(company).create({
            'name': 'Sites %s' % code, 'brand_categ_id': cls.brand.id, 'sage_company_code': code,
            'company_id': company.id}) for code, company in (('01', cls.c1), ('02', cls.c2), ('03', cls.c3))}
        cls.Warehouse = cls.env['rms.sage.warehouse']
        cls.Scan = cls.env['rms.stock.count.scan']

    def _line(self, code, serial, warehouse='A.7', state='nuevo'):
        return self.env['rms.sage.stock.line'].sudo().create({
            'snapshot_id': self.snap[code].id, 'is_current': True, 'warehouse_code': warehouse,
            'article_code': 'SITES-ART', 'model_code': 'SITES-ART', 'serial': serial, 'quantity': 1,
            'product_id': self.product.id, 'state': state, 'match_state': 'ok'})

    def _wh(self, sage_code, code):
        return self.Warehouse.search([('sage_company_code', '=', sage_code), ('code', '=', code)])

    def test_setup_links_three_companies_idempotent_and_undo(self):
        summary = self.Warehouse._setup_default_links()
        self.assertIn('01 A.7 -> RMS7', summary['linked'] + summary['created'])
        self.assertIn('02 A.7 -> ET7', summary['created'])
        self.assertIn('03 A.7 -> RJB7', summary['created'])
        self.assertIn('01 AL3 -> RMS3', summary['missing_odoo'])   # no existe en esta BD
        self.assertEqual(self._wh('02', 'A.7').location_id, self.wh['ET7'].lot_stock_id)
        self.assertEqual(self._wh('02', 'A.7').company_id, self.c2)
        self.assertEqual(self._wh('01', 'A.7').site_number, 7)
        self.assertEqual(self._wh('03', 'A.7').site_number, 7)
        again = self.Warehouse._setup_default_links()
        self.assertFalse(again['created'] or again['linked'])
        self.assertIn('02 A.7 -> ET7', again['unchanged'])
        undo = self.Warehouse._undo_default_links()
        self.assertTrue(undo['removed'] >= 2)
        self.assertFalse(self._wh('02', 'A.7'))
        self.assertFalse(self._wh('01', 'A.7').location_id)  # vuelve a como estaba (sin enlazar)

    def test_alias_al7_counts_as_a7(self):
        a7 = self._line('01', 'SITE-AL7-1', warehouse='AL7')
        dup_a = self._line('01', 'SITE-BOTH-1', warehouse='A.7')
        dup_b = self._line('01', 'SITE-BOTH-1', warehouse='AL7')
        self.Warehouse._setup_default_links()
        main = self._wh('01', 'A.7')
        self.assertEqual(self._wh('01', 'AL7').alias_of_id, main)
        self.assertEqual(a7.sage_warehouse_id, main)
        session = self.env['rms.stock.count.session'].create({'location_id': self.wh['RMS7'].lot_stock_id.id})
        verdict = self.Scan._sage_verdict(['SITE-AL7-1'], session, self.product, ['new'])[0]
        self.assertEqual(verdict['v'], 'ok')
        self.assertEqual(verdict['h'][0][1], 'A.7')
        # El mismo equipo con A.7 y con AL7 no es un duplicado.
        both = self.Scan._sage_verdict(['SITE-BOTH-1'], session, self.product, ['new'])[0]
        self.assertEqual(both['v'], 'ok')
        self.assertEqual(dup_a.dup_count, 1)
        self.assertEqual(dup_b.dup_count, 1)

    def test_progress_sums_the_three_companies_of_the_site(self):
        self._line('01', 'SITE-P-01')
        self._line('02', 'SITE-P-02')
        self._line('03', 'SITE-P-03', warehouse='AL7')
        self._line('01', 'SITE-P-MAD', warehouse='AL1')   # otra nave: no cuenta
        self.Warehouse._setup_default_links()
        session = self.env['rms.stock.count.session'].create({'location_id': self.wh['RMS7'].lot_stock_id.id})
        Operator = self.env['rms.stock.count.operator']
        operator = Operator.browse(Operator.scanner_join(session.id, 'Sevilla')['operator']['id'])
        progress = operator.scanner_progress()
        self.assertEqual(progress['site'], 'Sevilla (A.7)')
        self.assertEqual(progress['total'], 3)
        # Un equipo de Espacio en Sevilla leído desde un recuento de RMS: verde.
        result = self.Scan.scanner_register(operator.id, 'SITE-P-02')
        self.assertEqual(result['scan']['sage']['v'], 'ok')
        self.assertEqual(result['scan']['sage']['h'][0][0], '02')
        self.assertEqual(operator.scanner_progress()['counted'], 1)
        found = operator.scanner_sage_search('SITE-P')
        self.assertEqual({r['serial'] for r in found}, {'SITE-P-01', 'SITE-P-03'})

    def test_doubtful_warehouse_is_registered_but_not_linked(self):
        self._line('02', 'SITE-D-1', warehouse='A.4')
        summary = self.Warehouse._setup_default_links()
        doubtful = self._wh('02', 'A.4')
        self.assertTrue(doubtful)
        self.assertFalse(doubtful.location_id)
        self.assertIn('dudoso', doubtful.name)
        self.assertTrue(any(item.startswith('02 A.4') for item in summary['doubtful']))
