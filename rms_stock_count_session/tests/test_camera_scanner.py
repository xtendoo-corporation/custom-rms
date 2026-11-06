# -*- coding: utf-8 -*-

import base64

from odoo.tests import TransactionCase, tagged


# Imagen JPEG de 1 × 1: la captura viaja como base64, sin cabecera data:.
_SNAPSHOT = (
    '/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAP//////////////////////////////'
    '////////////////////////////////////////////////////////2wBDAf//'
    '////////////////////////////////////////////////////////////////'
    '////////////////////wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAA'
    'AAAAAAAAAAX/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIQAxAAAAF//8QAFBAB'
    'AAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABBQJ//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/a'
    'AAgBAwEBPwF//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAgEBPwF//8QAFBABAAAA'
    'AAAAAAAAAAAAAAAAAP/aAAgBAQAGPwJ//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgB'
    'AQABPyF//9oADAMBAAIAAwAAABD/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAEDAQE/'
    'EH//xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAECAQE/EH//xAAUEAEAAAAAAAAAAAAA'
    'AAAAAAAA/9oACAEBAAE/EH//2Q=='
)


@tagged('post_install', '-at_install')
class TestCameraScanner(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1,
        )
        cls.product = cls.env['product.product'].create({
            'name': 'RMSTEST Sony camera batch', 'is_storable': True,
            'tracking': 'serial', 'barcode': '027242792319',
        })
        cls.env['rms.product.scan.alias'].create({
            'product_tmpl_id': cls.product.product_tmpl_id.id,
            'code': 'P-81675340-G',
        })
        cls.session = cls.env['rms.stock.count.session'].create({
            'location_id': warehouse.lot_stock_id.id,
        })
        Operator = cls.env['rms.stock.count.operator']
        joined = Operator.scanner_join(cls.session.id, 'Camera test')
        cls.operator = Operator.browse(joined['operator']['id'])
        cls.Scan = cls.env['rms.stock.count.scan']

    def test_batch_registers_product_before_new_serial(self):
        results = self.Scan.scanner_register_batch(
            self.operator.id, ['S01-0040002-Z', 'P-81675340-G'], 'camera-order',
        )
        self.assertEqual([r['scan']['type'] for r in results], ['product_ref', 'serial'])
        self.assertEqual(results[0]['scan']['code'], 'P-81675340-G')
        serial = self.Scan.browse(results[1]['scan']['id'])
        self.assertEqual(serial.product_id, self.product)
        self.assertEqual(serial.lot_name, '0040002')
        self.assertTrue(serial.is_new_lot)
        self.assertLess(results[0]['scan']['id'], serial.id)

    def test_batch_orders_server_classified_serial(self):
        self.env['stock.lot'].create({
            'name': 'RMSTEST-EXISTING-SERIAL', 'product_id': self.product.id,
        })
        results = self.Scan.scanner_register_batch(
            self.operator.id, ['RMSTEST-EXISTING-SERIAL', '027242792319'],
            'camera-existing',
        )
        self.assertEqual([r['scan']['type'] for r in results], ['product_ref', 'serial'])
        self.assertEqual(results[1]['scan']['lot_name'], 'RMSTEST-EXISTING-SERIAL')

    def test_ignored_sscc_does_not_break_batch(self):
        results = self.Scan.scanner_register_batch(
            self.operator.id,
            ['S01-0040002-Z', '(00)050134930120831424', 'P-81675340-G'],
            'camera-sscc',
        )
        self.assertEqual([r['scan']['type'] for r in results],
                         ['ignored', 'product_ref', 'serial'])
        self.assertEqual(self.Scan.browse(results[-1]['scan']['id']).product_id, self.product)
        self.assertEqual(len(self.session.scan_ids), 3)

    def test_batch_retry_keeps_client_uids_and_does_not_duplicate(self):
        codes = ['S01-0040002-Z', 'P-81675340-G']
        first = self.Scan.scanner_register_batch(self.operator.id, codes, 'camera-retry')
        again = self.Scan.scanner_register_batch(self.operator.id, codes, 'camera-retry')
        self.assertEqual([r['status'] for r in again], ['resent', 'resent'])
        self.assertEqual([r['scan']['id'] for r in again], [r['scan']['id'] for r in first])
        self.assertEqual(len(self.session.scan_ids), 2)
        self.assertEqual(self.Scan.browse(first[0]['scan']['id']).client_uid, 'camera-retry:1')
        self.assertEqual(self.Scan.browse(first[1]['scan']['id']).client_uid, 'camera-retry:0')

    def test_snapshot_attached_to_first_scan_and_retry_is_idempotent(self):
        parameter = self.env['ir.config_parameter'].sudo()
        parameter.search([('key', '=', 'rms_stock_count_session.camera_snapshots')]).unlink()
        self.assertTrue(self.Scan.scanner_camera_config()['camera_snapshots'])
        results = self.Scan.scanner_register_batch(
            self.operator.id, ['S01-0040002-Z', 'P-81675340-G'], 'camera-photo',
        )
        first_id = results[0]['scan']['id']
        attachment_id = self.Scan.scanner_attach_snapshot(first_id, _SNAPSHOT)
        attachment = self.env['ir.attachment'].browse(attachment_id)
        self.assertTrue(attachment.exists())
        self.assertEqual(attachment.res_model, 'rms.stock.count.scan')
        self.assertEqual(attachment.res_id, first_id)
        self.assertEqual(attachment.mimetype, 'image/jpeg')
        self.assertEqual(base64.b64decode(attachment.datas), base64.b64decode(_SNAPSHOT))
        self.assertEqual(self.Scan.scanner_attach_snapshot(first_id, _SNAPSHOT), attachment.id)
        self.assertEqual(self.env['ir.attachment'].search_count([
            ('res_model', '=', 'rms.stock.count.scan'), ('res_id', '=', first_id),
        ]), 1)

    def test_snapshot_parameter_disables_upload(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'rms_stock_count_session.camera_snapshots', 'False',
        )
        self.assertFalse(self.Scan.scanner_camera_config()['camera_snapshots'])
        result = self.Scan.scanner_register(self.operator.id, '027242792319', 'camera-disabled')
        self.assertFalse(self.Scan.scanner_attach_snapshot(result['scan']['id'], _SNAPSHOT))
        self.assertFalse(self.env['ir.attachment'].search_count([
            ('res_model', '=', 'rms.stock.count.scan'), ('res_id', '=', result['scan']['id']),
        ]))

    def _camera_batch(self, codes, uid):
        return self.Scan.scanner_register_batch(
            self.operator.id, codes, uid, source='camera',
        )

    def test_real_camera_frames_never_invent_serials(self):
        # Keep each frame independent. RMU's complete-label frame is added
        # separately: its real isolated serial must remain pending as well.
        self.product.product_tmpl_id.rms_scan_alias_ids.unlink()
        self.product.write({'name': 'RMU-01', 'barcode': '0027242792319'})
        products = {'RMU-01': self.product}
        fixtures = [
            ('DWT-P01N/33', False, 'P81664462J'),
            ('RMU-01', '0027242792319', 'P81655988W'),
            ('DWT-P30/H', False, 'P81675340G'),
            ('CU-C31', False, 'P81658081J'),
            ('CU-F31', '0027242849396', 'P81658283N'),
            ('UWP-D26/K42', '4548736106581', 'P81671585N'),
            ('AN-01', '0027242792302', 'P81655885S'),
        ]
        for name, barcode, alias in fixtures:
            product = products.get(name)
            if product is None:
                product = self.env['product.product'].create({
                    'name': name, 'is_storable': True,
                    'tracking': 'serial', 'barcode': barcode,
                })
                products[name] = product
            self.env['rms.product.scan.alias'].create({
                'product_tmpl_id': product.product_tmpl_id.id, 'code': alias,
            })
        frames = [
            ['P81664462J', 'S010040202.'],
            ['0027242792319', 'P81655988W'],
            ['S010012811%'],
            ['P81675340G', 'S010040002Z'],
            ['P81675340G'],
            ['4905524891669', 'P81658081J', 'S010011650%'],
            ['0027242849396', 'P81658283N', 'S0100119298'],
            ['0027242849396', 'P81658283N'],
            ['0011142849396', '4905524891737'],
            ['0126019000098'],
            ['P81671585N', '4548736106581', 'S010000000T',
             'S0104025434', 'S0104013756'],
            ['0027242792302', 'P81655885S', 'S010101699C'],
            ['S010040003-'],
        ]
        results = []
        for index, frame in enumerate(frames):
            results.append(self._camera_batch(frame, 'real-frame-%s' % index))
        self.assertEqual(results[2][0]['status'], 'unknown')
        self.assertEqual(results[2][0]['scan']['message'], 'sin producto en el encuadre')
        self._camera_batch(
            ['0027242792319', 'P81655988W', 'S010012811%'], 'rmu-complete-label',
        )
        serials = self.session.scan_ids.filtered(lambda scan: scan.scan_type == 'serial')
        self.assertEqual({(scan.product_id.id, scan.lot_name) for scan in serials}, {
            (products['DWT-P01N/33'].id, '0040202'),
            (products['RMU-01'].id, '0012811'),
            (products['DWT-P30/H'].id, '0040002'),
            (products['CU-C31'].id, '0011650'),
            (products['CU-F31'].id, '0011929'),
            (products['AN-01'].id, '0101699'),
        })
        self.assertEqual(len(serials), 6)
        for code in ('4905524891669', '4905524891737', '0011142849396', '0126019000098'):
            scans = self.session.scan_ids.filtered(lambda scan: scan.code == code)
            self.assertTrue(scans)
            self.assertEqual(set(scans.mapped('scan_type')), {'unknown'})
            self.assertEqual(set(scans.mapped('message')), {'código de producto desconocido'})
            self.assertFalse(any(scans.mapped('lot_name')))
        kit_serials = [r for r in results[10] if r['scan']['lot_name']]
        self.assertEqual(len(kit_serials), 2)
        self.assertTrue(all(r['status'] == 'unknown' for r in kit_serials))
        self.assertTrue(all(r['scan']['message'] == 'varios números de serie en el encuadre'
                            for r in kit_serials))
        self.assertEqual(results[-1][0]['status'], 'unknown')
        self.assertEqual(results[-1][0]['scan']['message'], 'sin producto en el encuadre')
        self.assertFalse(self.Scan.browse(results[-1][0]['scan']['id']).product_id)

    def test_camera_rejects_multiple_products_and_ignores_non_serials(self):
        other = self.env['product.product'].create({
            'name': 'RMSTEST second frame product', 'is_storable': True,
            'tracking': 'serial', 'barcode': 'RMSTEST-SECOND-PRODUCT',
        })
        results = self._camera_batch(
            ['P-81675340-G', other.barcode, 'S010040003-'], 'camera-two-products',
        )
        self.assertEqual(results[-1]['scan']['type'], 'unknown')
        self.assertEqual(results[-1]['scan']['message'], 'varios productos en el encuadre')
        results = self._camera_batch(
            ['P-81675340-G', 'S010040002Z', 'S010000000T', '(00)050134930120831424'],
            'camera-ignore-not-candidates',
        )
        self.assertEqual([r['scan']['lot_name'] for r in results if r['status'] == 'ok'],
                         ['0040002'])
        self.assertEqual(sum(r['status'] == 'ignored' for r in results), 2)

    def test_camera_existing_serial_resolves_without_product_and_retry_is_idempotent(self):
        self.env['stock.lot'].create({
            'name': '0040002', 'product_id': self.product.id,
        })
        first = self._camera_batch(['S010040002Z'], 'camera-existing-alone')
        self.assertEqual(first[0]['status'], 'ok')
        self.assertEqual(first[0]['scan']['lot_name'], '0040002')
        again = self._camera_batch(['S010040002Z'], 'camera-existing-alone')
        self.assertEqual(again[0]['status'], 'resent')
        self.assertEqual(again[0]['scan']['id'], first[0]['scan']['id'])

    def test_camera_gtin_shape_blocked_unless_explicit_serial_rule(self):
        self.Scan.scanner_register(self.operator.id, 'P-81675340-G')
        for length in (8, 12, 13, 14):
            result = self._camera_batch(['9' * length], 'camera-gtin-%s' % length)[0]
            self.assertEqual(result['status'], 'unknown')
            self.assertEqual(result['scan']['message'], 'código de producto desconocido')
        self.env['stock.lot'].create({
            'name': '9999999999999', 'product_id': self.product.id,
        })
        existing_gtin = self._camera_batch(['9999999999999'], 'camera-existing-gtin')[0]
        self.assertEqual(existing_gtin['status'], 'unknown')
        self.assertEqual(existing_gtin['scan']['message'], 'código de producto desconocido')
        self.env['rms.scan.rule'].create({
            'name': 'RMSTEST explicit numeric serial', 'sequence': 0,
            'pattern': '(?P<serial>87654321)', 'action': 'serial',
        })
        result = self._camera_batch(['87654321', 'P-81675340-G'], 'camera-explicit-rule')
        self.assertEqual(result[-1]['status'], 'ok')
        self.assertEqual(result[-1]['scan']['lot_name'], '87654321')
        # Keyboard/PDA keeps its established current-product fallback.
        pda = self.Scan.scanner_register(self.operator.id, '9999999999999')
        self.assertEqual(pda['status'], 'ok')
        self.assertEqual(pda['scan']['lot_name'], '9999999999999')

    def test_camera_existing_serial_counts_towards_frame_ambiguity(self):
        self.env['stock.lot'].create({'name': '0040002', 'product_id': self.product.id})
        results = self._camera_batch(
            ['P-81675340-G', 'S010040002Z', 'S010040003-'], 'camera-existing-and-new',
        )
        existing = next(r for r in results if r['scan']['lot_name'] == '0040002')
        new = next(r for r in results if r['scan']['lot_name'] == '0040003')
        self.assertEqual(existing['status'], 'ok')
        self.assertEqual(new['status'], 'unknown')
        self.assertEqual(new['scan']['message'], 'varios números de serie en el encuadre')

    def test_camera_new_serial_retry_does_not_duplicate(self):
        codes = ['S010040002Z', 'P-81675340-G']
        first = self._camera_batch(codes, 'camera-new-retry')
        again = self._camera_batch(codes, 'camera-new-retry')
        self.assertEqual([r['status'] for r in again], ['resent', 'resent'])
        self.assertEqual([r['scan']['id'] for r in again], [r['scan']['id'] for r in first])
        self.assertEqual(len(self.session.scan_ids), 2)

    def test_scanner_history_includes_all_own_session_readings(self):
        self.Scan.create([
            {'session_id': self.session.id, 'operator_id': self.operator.id,
             'code': 'RMSTEST-HISTORY-%s' % index, 'scan_type': 'unknown'}
            for index in range(65)
        ])
        other = self.env['rms.stock.count.operator'].create({
            'session_id': self.session.id, 'name': 'Other history operator',
        })
        self.Scan.create({
            'session_id': self.session.id, 'operator_id': other.id,
            'code': 'RMSTEST-OTHER-OPERATOR', 'scan_type': 'unknown',
        })
        self.Scan.create({
            'session_id': self.session.id, 'operator_id': self.operator.id,
            'code': 'RMSTEST-LOCATION', 'scan_type': 'location',
        })
        history = self.Scan.scanner_history(self.operator.id)
        self.assertEqual(len(history), 65)
        self.assertEqual({scan['code'] for scan in history},
                         {'RMSTEST-HISTORY-%s' % index for index in range(65)})
        self.assertEqual([scan['id'] for scan in history],
                         sorted((scan['id'] for scan in history), reverse=True))
