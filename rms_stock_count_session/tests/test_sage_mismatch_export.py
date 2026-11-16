# -*- coding: utf-8 -*-
"""Excel de descuadres: una hoja por tipo de diferencia con Sage."""
import base64
import io

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSageMismatchExport(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Warehouse = cls.env['stock.warehouse']
        cls.wh7 = Warehouse.create({'name': 'TEST RMS7', 'code': 'RMS7'})
        cls.wh1 = Warehouse.create({'name': 'TEST RMS1', 'code': 'RMS1'})
        cls.brand = cls.env['product.category'].create({'name': 'RMSTEST Excel Brand'})
        cls.product = cls.env['product.product'].create({'name': 'EXCEL GALAXY', 'categ_id': cls.brand.id,
                                                         'is_storable': True, 'tracking': 'serial'})
        cls.snapshot = cls.env['rms.sage.snapshot'].create({
            'name': 'Excel test', 'brand_categ_id': cls.brand.id, 'sage_company_code': '01'})
        for serial, warehouse, state, extra in (
                ('XL-OK', 'A.7', 'nuevo', {}),
                ('XL-MISSING', 'A.7', 'nuevo', {}),
                ('XL-DEMO', 'A.7', 'demo', {}),
                ('XL-DEP', 'A.7', 'nuevo', {'in_deposit': True}),
                ('XL-MADRID', 'AL1', 'nuevo', {}),
                ('XL-NEG', 'A.7', 'nuevo', {'quantity': -1})):
            cls.env['rms.sage.stock.line'].create(dict({
                'snapshot_id': cls.snapshot.id, 'is_current': True, 'warehouse_code': warehouse,
                'article_code': 'XL-ART', 'model_code': 'XL-ART', 'serial': serial, 'quantity': 1,
                'product_id': cls.product.id, 'state': state, 'match_state': 'ok'}, **extra))
        cls.env['rms.sage.warehouse']._setup_default_links()
        cls.session = cls.env['rms.stock.count.session'].create({'location_id': cls.wh7.lot_stock_id.id})
        Operator = cls.env['rms.stock.count.operator']
        cls.operator = Operator.browse(Operator.scanner_join(cls.session.id, 'Excel')['operator']['id'])
        Scan = cls.env['rms.stock.count.scan']
        cls.operator.current_product_id = cls.product
        for code in ('XL-OK', 'XL-DEMO', 'XL-DEP', 'XL-MADRID', 'XL-ALTA'):
            Scan.scanner_register(cls.operator.id, code)

    def _sheets(self, **vals):
        from openpyxl import load_workbook
        wizard = self.env['rms.sage.mismatch.export'].create(vals)
        wizard.action_export()
        self.assertTrue(wizard.filename.endswith('.xlsx'))
        book = load_workbook(io.BytesIO(base64.b64decode(wizard.file)))
        return {name: [[cell.value for cell in row] for row in book[name].iter_rows(min_row=2)]
                for name in book.sheetnames}

    def _serials(self, rows, column=6):
        return {row[column] for row in rows}

    def test_every_kind_goes_to_its_sheet(self):
        sheets = self._sheets()
        self.assertEqual(self._serials(sheets['No leídos']), {'XL-MISSING'})
        self.assertEqual(self._serials(sheets['Altas']), {'XL-ALTA'})
        self.assertEqual(self._serials(sheets['Estado distinto']), {'XL-DEMO'})
        self.assertEqual(self._serials(sheets['En depósito y en nave']), {'XL-DEP'})
        self.assertEqual(self._serials(sheets['En otra nave']), {'XL-MADRID'})
        self.assertEqual(self._serials(sheets['Negativos en Sage']), {'XL-NEG'})
        self.assertFalse(sheets['Duplicados en Sage'])
        summary = {row[0]: row[1] for row in sheets['Resumen'] if row[0] and isinstance(row[1], int)}
        self.assertEqual(summary['No leídos'], 1)
        self.assertEqual(summary['Altas'], 1)

    def test_filter_by_site(self):
        madrid = self._sheets(site_number='1')
        # Sage dice Madrid y se leyó en Sevilla: sale al pedir cualquiera de las dos naves.
        self.assertEqual(self._serials(madrid['En otra nave']), {'XL-MADRID'})
        self.assertFalse(madrid['No leídos'])
        self.assertFalse(madrid['Altas'])
        sevilla = self._sheets(site_number='7', sage_company_code='01')
        self.assertEqual(self._serials(sevilla['No leídos']), {'XL-MISSING'})
        self.assertEqual(self._serials(sevilla['Altas']), {'XL-ALTA'})
        self.assertFalse(self._sheets(sage_company_code='03')['No leídos'])
