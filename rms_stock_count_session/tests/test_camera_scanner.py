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
