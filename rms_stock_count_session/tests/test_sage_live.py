# -*- coding: utf-8 -*-
"""Sage en vivo: el extractor del NAS envía existencias, depósitos y
movimientos de Sage por la API."""
from datetime import date, timedelta

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestSageLive(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Run = cls.env['rms.sage.sync.run']
        cls.Line = cls.env['rms.sage.stock.line']
        cls.brand = cls.env['product.category'].create({'name': 'LIVE BRAND'})
        cls.galaxy = cls.env['product.product'].create({
            'name': 'LIVE GALAXY', 'default_code': 'LIVE-GLX', 'categ_id': cls.brand.id,
            'is_storable': True, 'tracking': 'serial'})
        warehouse = cls.env['stock.warehouse'].search([('company_id', '=', cls.env.company.id)], limit=1)
        cls.session = cls.env['rms.stock.count.session'].create({'location_id': warehouse.lot_stock_id.id})
        Operator = cls.env['rms.stock.count.operator']
        cls.operator = Operator.browse(Operator.scanner_join(cls.session.id, 'Sage en vivo')['operator']['id'])
        cls.Scan = cls.env['rms.stock.count.scan']

    def _rows(self, *serials, warehouse='A.7', article='LIVE-GLX'):
        return [{'warehouse_code': warehouse, 'article_code': article, 'article_name': 'Live galaxy',
                 'serial': serial, 'quantity': 1} for serial in serials]

    def _current(self, serial, kind='stock'):
        return self.Line.search([('serial', '=', serial), ('is_current', '=', True), ('stock_kind', '=', kind)])

    def test_push_stock_replaces_company_and_kind_and_is_idempotent(self):
        res = self.Run.push_stock('01', 'stock', self._rows('LV-1', 'LV-2') + [
            {'warehouse_code': 'A.7', 'article_code': 'CABLE-LIVE', 'quantity': 5},
            {'warehouse_code': 'A.7', 'article_code': 'CABLE-LIVE', 'quantity': 3}], '2026-11-14')
        self.assertEqual(res['status'], 'ok')
        self.assertTrue(self._current('LV-1'))
        self.assertEqual(self._current('LV-1').product_id, self.galaxy)
        cable = self.Line.search([('article_code', '=', 'CABLE-LIVE'), ('is_current', '=', True)])
        self.assertEqual(cable.quantity, 8)
        # Mismo contenido: no hace nada.
        again = self.Run.push_stock('01', 'stock', self._rows('LV-2', 'LV-1') + [
            {'warehouse_code': 'A.7', 'article_code': 'CABLE-LIVE', 'quantity': 5},
            {'warehouse_code': 'A.7', 'article_code': 'CABLE-LIVE', 'quantity': 3}])
        self.assertEqual(again['status'], 'nochange')
        # Otra empresa y los depósitos no tocan las existencias de la 01.
        self.Run.push_stock('02', 'stock', self._rows('LV-9'))
        self.Run.push_stock('01', 'deposit', [dict(self._rows('LV-2')[0], partner_name='ACME AUDIO')])
        self.assertTrue(self._current('LV-1'))
        self.assertTrue(self._current('LV-2').in_deposit)
        self.assertEqual(self._current('LV-2', 'deposit').partner_name, 'ACME AUDIO')
        # Nueva foto de la 01 sin LV-1: sustituye la anterior.
        self.Run.push_stock('01', 'stock', self._rows('LV-2'))
        self.assertFalse(self._current('LV-1'))
        self.assertTrue(self._current('LV-2'))
        self.assertTrue(self._current('LV-9'))
        self.assertEqual(self.Run.search_count([('state', '=', 'nochange')]), 1)

    def test_push_moves_upsert_and_watermark(self):
        row = {'sage_key': 'K-1', 'sage_table': 'ltdepve', 'sage_modified': '2026-11-14 09:00:00',
               'sage_company_code': '01', 'move_type': 'deposit', 'move_date': '2026-11-14',
               'article_code': 'LIVE-GLX', 'serial': 'MV-1', 'quantity': 1, 'warehouse_from': 'A.7',
               'document': 'D-77', 'partner_name': 'ACME AUDIO'}
        res = self.Run.push_moves([row, dict(row, sage_key='K-2', serial='MV-2', move_type='bogus')])
        self.assertEqual(res['created'], 1)
        move = self.env['rms.sage.serial.move'].search([('sage_key', '=', 'K-1')])
        self.assertEqual(move.serial_normalized, 'MV1')
        self.assertEqual(move.product_id, self.galaxy)
        self.assertEqual(self.Run.push_moves([row])['created'], 0)
        res = self.Run.push_moves([dict(row, sage_modified='2026-11-14 10:00:00', document='D-78')])
        self.assertEqual(res['updated'], 1)
        self.assertEqual(move.document, 'D-78')
        self.assertEqual(self.Run.last_watermark(), {'ltdepve': '2026-11-14 10:00:00'})
        with self.assertRaises(UserError):
            self.Run.push_moves([row] * 5001)

    def test_moved_after_count_in_checklist_extra_and_scanner(self):
        self.Run.push_stock('01', 'stock', self._rows('MA-1', 'MA-2'))
        self.operator.current_product_id = False
        scan = self.Scan.browse(self.Scan.scanner_register(self.operator.id, 'MA-1')['scan']['id'])
        self.assertEqual(scan.product_id, self.galaxy)
        today = scan.scanned_at.date()
        self.env['rms.sage.serial.move'].create({
            'sage_key': 'S-1', 'move_type': 'deposit', 'move_date': today, 'article_code': 'LIVE-GLX',
            'serial': 'MA-1', 'document': 'DEP-5', 'partner_name': 'ACME AUDIO'})
        self.env['rms.sage.serial.move'].create({
            'sage_key': 'S-2', 'move_type': 'sale', 'move_date': today - timedelta(days=10),
            'article_code': 'LIVE-GLX', 'serial': 'MA-2'})
        self.env.flush_all()
        self.env.invalidate_all()
        Checklist = self.env['rms.sage.checklist']
        row = Checklist.search([('serial', '=', 'MA-1')])
        self.assertTrue(row.moved_after_count)
        self.assertEqual(row.moved_type, 'deposit')
        self.assertEqual(row.moved_partner, 'ACME AUDIO')
        self.assertFalse(Checklist.search([('serial', '=', 'MA-2')]).moved_after_count,
                         'Un movimiento anterior a la lectura (o sin lectura) no cuenta')
        payload = scan._scanner_payload()
        self.assertIn('ACME AUDIO', payload['moved_after'])
        history = self.Scan.scanner_history(self.operator.id)
        self.assertIn('depósito a ACME AUDIO', [p for p in history if p['id'] == scan.id][0]['moved_after'])
        # Sage ya no lo tiene en existencias: en altas sale como movido, no como alta real.
        self.Run.push_stock('01', 'stock', self._rows('MA-2'))
        self.env.invalidate_all()
        extra = self.env['rms.sage.checklist.extra'].search([('scan_id', '=', scan.id)])
        self.assertTrue(extra.moved_after_count)
        self.assertEqual(extra.moved_type, 'deposit')

    def test_api_requires_inventory_manager(self):
        user = new_test_user(self.env, login='live_user', groups='stock.group_stock_user')
        with self.assertRaises(AccessError):
            self.Run.with_user(user).push_stock('01', 'stock', self._rows('X-1'))
        with self.assertRaises(AccessError):
            self.Run.with_user(user).push_moves([])
        with self.assertRaises(AccessError):
            self.Run.with_user(user).last_watermark()
        with self.assertRaises(UserError):
            self.Run.push_stock('99', 'stock', [])

    def test_csv_import_still_works_through_shared_path(self):
        import base64
        raw = ('Almacén;Artículo;Nombre artículo;Lotes;Unidades\n'
               '000;LIVE-GLX;Live galaxy;;\n'
               'A.7;;;;1,00\n'
               ';;;CSV-LIVE-1;1,00\n').encode('utf-8')
        self.env['rms.stock.count.sage.import'].create({
            'filename': 'live.csv', 'file_data': base64.b64encode(raw)}).action_import()
        line = self._current('CSV-LIVE-1')
        self.assertEqual(line.product_id, self.galaxy)
        self.assertTrue(line.snapshot_id.attachment)
