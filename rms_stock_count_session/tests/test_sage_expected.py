# -*- coding: utf-8 -*-

import base64
from io import BytesIO

from openpyxl import Workbook

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSageExpected(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1,
        )
        cls.session = cls.env['rms.stock.count.session'].create({
            'location_id': warehouse.lot_stock_id.id,
        })
        Operator = cls.env['rms.stock.count.operator']
        joined = Operator.scanner_join(cls.session.id, 'Sage test')
        cls.operator = Operator.browse(joined['operator']['id'])
        cls.Scan = cls.env['rms.stock.count.scan']
        cls.Expected = cls.env['rms.stock.count.expected']
        Product = cls.env['product.product']
        cls.dwm = Product.create({
            'name': 'RMSTEST DWM', 'default_code': 'DWM-02N/33',
            'is_storable': True, 'tracking': 'serial',
        })
        cls.antenna = Product.create({
            'name': 'AN-01', 'is_storable': True, 'tracking': 'none',
        })
        cls.wd = Product.create({
            'name': 'WD-850A', 'is_storable': True, 'tracking': 'serial',
        })
        cls.env['rms.product.scan.alias'].create({
            'product_tmpl_id': cls.wd.product_tmpl_id.id, 'code': 'WD-850A',
        })

    def _import_fixture(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = 'Valoración de stocks'
        for row in [
            ['Almacén', 'Artículo', 'Nombre artículo', 'Lotes',
             'Unidades', 'Precio', 'Total', 'Tipo registro'],
            ['AL1', 'D-SONY-DWM-02N/33', 'Transmisor', None, 2, 100, 200, None],
            [None, None, None, '0040579', 1, None, None, None],
            [None, None, None, '0040580', 1, None, None, None],
            ['AL1', 'SONY-AN-01', 'Antena', None, 3, 10, 30, None],
            [None, None, None, 'S/N', 1, None, None, None],
            [None, None, None, 'S/N', 1, None, None, None],
            [None, None, None, 'S/N', 1, None, None, None],
            ['AL1', '2M-SONY-WD-850A', 'Amplificador', None, 1, 75, 75, None],
            [None, None, None, '0000123', 1, None, None, None],
            ['A.7', None, None, None, 1, None, None, None],
            [None, None, None, '0000124', 1, None, None, None],
        ]:
            sheet.append(row)
        stream = BytesIO()
        workbook.save(stream)
        workbook.close()
        wizard = self.env['rms.stock.count.sage.import'].create({
            'session_id': self.session.id, 'filename': 'sage_valoracion_sony_ejemplo.xlsx',
            'file_data': base64.b64encode(stream.getvalue()),
        })
        wizard.action_import()
        return self.session.expected_ids

    def test_import_hierarchical_sage_rows_and_replace(self):
        expected = self._import_fixture()
        self.assertEqual(len(expected), 5)
        demo = expected.filtered(lambda line: line.article_code == 'D-SONY-DWM-02N/33')
        self.assertEqual(set(demo.mapped('serial')), {'0040579', '0040580'})
        self.assertEqual(set(demo.mapped('serial_normalized')), {'40579', '40580'})
        self.assertEqual(set(demo.mapped('model_code')), {'DWM-02N/33'})
        self.assertEqual(set(demo.mapped('state_hint')), {'Demo'})
        self.assertEqual(demo.product_id, self.dwm)
        self.assertTrue(all(line.quantity == 1 and line.cost == 100 for line in demo))
        antenna = expected.filtered(lambda line: line.product_id == self.antenna)
        self.assertEqual(len(antenna), 1)
        self.assertFalse(antenna.serial)
        self.assertEqual(antenna.quantity, 3)
        self.assertEqual(antenna.state_hint, 'Nuevo')
        used = expected.filtered(lambda line: line.product_id == self.wd)
        self.assertEqual(set(used.mapped('warehouse_code')), {'AL1', 'A.7'})
        self.assertEqual(set(used.mapped('state_hint')), {'2Mano'})
        self.assertEqual(set(used.mapped('serial')), {'0000123', '0000124'})
        old_ids = expected.ids
        other_session = self.env['rms.stock.count.session'].create({
            'location_id': self.session.location_id.id,
        })
        other_line = self.Expected.create({
            'session_id': other_session.id, 'warehouse_code': 'AL1', 'article_code': 'UNRESOLVED',
            'model_code': 'UNRESOLVED', 'quantity': 4,
        })
        again = self._import_fixture()
        self.assertEqual(len(again), 5)
        self.assertFalse(self.Expected.browse(old_ids).exists())
        self.assertTrue(other_line.exists())

    def test_sage_suggestion_assigns_serial_and_learns_frame_part(self):
        self._import_fixture()
        results = self.Scan.scanner_register_batch(
            self.operator.id, ['P81672643J', 'P81672643J', 'S010040579B'],
            'sage-suggestion-frame', source='camera',
        )
        serial = self.Scan.browse(next(
            result['scan']['id'] for result in results
            if result['scan']['lot_name'] == '0040579'
        ))
        self.assertEqual(serial.scan_type, 'unknown')
        self.assertEqual(serial.sage_suggestion_product_id, self.dwm)
        self.assertIn('AL1', serial.sage_suggestion)
        self.assertIn('Demo', serial.sage_suggestion)
        serial.action_use_sage_suggestion()
        self.assertEqual(serial.scan_type, 'serial')
        self.assertEqual(serial.product_id, self.dwm)
        self.assertEqual(serial.lot_name, '0040579')
        part = self.session.scan_ids.filtered(lambda scan: scan.code == 'P81672643J')
        self.assertEqual(len(part), 2)
        self.assertEqual(set(part.mapped('scan_type')), {'product_ref'})
        self.assertEqual(part.product_id, self.dwm)
        self.assertTrue(self.env['rms.product.scan.alias'].search_count([
            ('product_tmpl_id', '=', self.dwm.product_tmpl_id.id),
            ('code_normalized', '=', 'P81672643J'),
        ]))

    def test_suggestion_multiple_products_has_text_without_action_candidate(self):
        self._import_fixture()
        self.Expected.create({
            'session_id': self.session.id, 'article_code': 'WD-850A',
            'model_code': 'WD-850A', 'warehouse_code': 'A.7',
            'serial': '00-40579', 'quantity': 1,
        })
        result = self.Scan.scanner_register_batch(
            self.operator.id, ['S010040579B'], 'sage-ambiguous', source='camera',
        )[0]
        scan = self.Scan.browse(result['scan']['id'])
        self.assertTrue(scan.sage_suggestion)
        self.assertFalse(scan.sage_suggestion_product_id)

    def test_import_refreshes_suggestions_for_existing_unknown(self):
        result = self.Scan.scanner_register_batch(
            self.operator.id, ['S010040579B'], 'sage-before-import', source='camera',
        )[0]
        scan = self.Scan.browse(result['scan']['id'])
        self.assertFalse(scan.sage_suggestion_product_id)
        self._import_fixture()
        self.assertEqual(scan.sage_suggestion_product_id, self.dwm)

    def test_no_serial_article_keeps_total_quantity(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(['Almacén', 'Artículo', 'Nombre artículo', 'Lotes',
                      'Unidades', 'Precio', 'Total', 'Tipo registro'])
        sheet.append(['AL1', 'SONY-AN-01', 'Antena', None, 5, 10, 50, None])
        sheet.append(['A.7', None, None, None, 2, None, None, None])
        stream = BytesIO()
        workbook.save(stream)
        workbook.close()
        self.env['rms.stock.count.sage.import'].create({
            'session_id': self.session.id, 'filename': 'sin_series.xlsx',
            'file_data': base64.b64encode(stream.getvalue()),
        }).action_import()
        expected = self.session.expected_ids
        self.assertEqual(len(expected), 2)
        self.assertEqual({line.warehouse_code: line.quantity for line in expected},
                         {'AL1': 5, 'A.7': 2})
        self.assertFalse(any(expected.mapped('serial')))
        self.assertEqual(expected.product_id, self.antenna)

    def test_sage_crossing_reports_counted_wrong_product_missing_and_extra(self):
        self._import_fixture()
        self.Scan.create([
            {'session_id': self.session.id, 'operator_id': self.operator.id,
             'code': serial, 'scan_type': 'serial', 'product_id': product.id,
             'lot_name': serial, 'quantity': 1, 'ignored': ignored}
            for serial, product, ignored in [
                ('0040579', self.dwm, False),
                ('0040580', self.wd, False),
                ('0099999', self.dwm, False),
                ('0000123', self.wd, True),
            ]
        ])
        other = self.env['rms.stock.count.operator'].create({
            'session_id': self.session.id, 'name': 'Second Sage operator',
        })
        self.Scan.create({
            'session_id': self.session.id, 'operator_id': other.id,
            'code': '0040579', 'scan_type': 'serial', 'product_id': self.dwm.id,
            'lot_name': '0040579', 'quantity': 1,
        })
        action = self.session.action_view_sage()
        self.assertEqual(action['res_model'], 'rms.stock.count.sage.line')
        lines = self.env[action['res_model']].search(action['domain'])
        self.assertEqual(len(lines), 6)
        counted = lines.filtered(lambda line: line.serial == '0040579')
        self.assertEqual(counted.status, 'counted')
        self.assertEqual(counted.counted_qty, 1)
        wrong = lines.filtered(lambda line: line.serial == '0040580')
        self.assertEqual(wrong.status, 'wrong_product')
        self.assertEqual(wrong.product_id, self.dwm)
        self.assertEqual(wrong.counted_product_id, self.wd)
        missing = lines.filtered(lambda line: line.serial == '0000123')
        self.assertEqual(missing.status, 'missing')
        extra = lines.filtered(lambda line: line.status == 'unexpected')
        self.assertEqual(len(extra), 1)
        self.assertEqual(extra.product_id, self.dwm)
        self.assertEqual(extra.counted_qty, 1)
        self.assertEqual(len(lines.filtered(lambda line: line.status == 'missing')), 3)
        # Opening the smart button again rebuilds the same report without duplication.
        self.session.action_view_sage()
        self.assertEqual(len(self.session.sage_line_ids), 6)

    def test_sage_crossing_partial_unserialized_quantity_remains_missing(self):
        self._import_fixture()
        self.Scan.create({
            'session_id': self.session.id, 'operator_id': self.operator.id,
            'code': 'AN-01', 'scan_type': 'product', 'product_id': self.antenna.id,
            'quantity': 1,
        })
        self.session.action_view_sage()
        antenna = self.session.sage_line_ids.filtered(
            lambda line: line.product_id == self.antenna
        )
        self.assertEqual(len(antenna), 1)
        self.assertEqual(antenna.status, 'missing')
        self.assertEqual(antenna.expected_qty, 3)
        self.assertEqual(antenna.counted_qty, 1)

    def test_expected_resolves_same_reference_variant_using_sage_state(self):
        attribute = self.env['product.attribute'].create({
            'name': 'RMSTEST Sage Estado', 'create_variant': 'always',
            'value_ids': [(0, 0, {'name': 'Nuevo'}), (0, 0, {'name': 'Demo'}),
                          (0, 0, {'name': '2ª Mano'})],
        })
        template = self.env['product.template'].create({
            'name': 'RMSTEST Sage variant model', 'is_storable': True,
            'tracking': 'serial',
            'attribute_line_ids': [(0, 0, {
                'attribute_id': attribute.id,
                'value_ids': [(6, 0, attribute.value_ids.ids)],
            })],
        })
        template.product_variant_ids.write({'default_code': 'RMSTEST-SAGE-VARIANTS'})
        for state, variant_value in [('Nuevo', 'Nuevo'), ('Demo', 'Demo'), ('2Mano', '2ª Mano')]:
            line = self.Expected.create({
                'session_id': self.session.id, 'warehouse_code': 'AL1',
                'article_code': 'RMSTEST-SAGE-VARIANTS',
                'model_code': 'RMSTEST-SAGE-VARIANTS', 'state_hint': state,
                'serial': '0000001', 'quantity': 1,
            })
            expected_variant = template.product_variant_ids.filtered(
                lambda product: variant_value in product.product_template_attribute_value_ids.mapped('name')
            )
            self.assertEqual(line.product_id, expected_variant)
