# -*- coding: utf-8 -*-
"""Robustez del escáner: un reenvío nunca duplica (mismo client_uid en todos
los caminos), el nombre del operario no distingue mayúsculas/acentos/espacios
y "FALTAN" al terminar el recorrido coincide con el marcador de la nave."""

from psycopg2 import IntegrityError

from odoo.exceptions import ConcurrencyError
from odoo.tests import tagged
from odoo.tools import mute_logger

from .test_sage_sites import TestSageSites


@tagged('post_install', '-at_install')
class TestScannerRobustness(TestSageSites):

    def _operator(self, session, name='Robusto'):
        Operator = self.env['rms.stock.count.operator']
        return Operator.browse(Operator.scanner_join(session.id, name)['operator']['id'])

    def _session(self):
        self.Warehouse._setup_default_links()
        return self.env['rms.stock.count.session'].create({'location_id': self.wh['RMS7'].lot_stock_id.id})

    def test_operator_name_ignores_case_accents_and_spaces(self):
        session = self._session()
        first = self._operator(session, 'PRUEBA AUTO 9e')
        self.Scan.scanner_register(first.id, 'ROB-NOMBRE-1', 'uid-nombre-1')
        for name in ('prueba auto 9E ', '  Prueba   Auto 9E', 'pruebaauto9e', 'PRUÉBA AUTÓ 9E'):
            again = self.env['rms.stock.count.operator'].scanner_join(session.id, name)
            self.assertEqual(again['operator']['id'], first.id, name)
            self.assertEqual(again['operator']['name'], 'PRUEBA AUTO 9e')
            self.assertEqual(len(again['recent']), 1)
        self.assertEqual(len(session.operator_ids), 1)
        other = self._operator(session, 'Prueba Auto 9F')
        self.assertNotEqual(other, first)

    def test_resend_never_duplicates_single_reading(self):
        self._line('01', 'ROB-DUP-01')
        session = self._session()
        operator = self._operator(session)
        first = self.Scan.scanner_register(operator.id, 'ROB-DUP-01', 'uid-1')
        self.assertEqual(first['status'], 'ok')
        again = self.Scan.scanner_register(operator.id, 'ROB-DUP-01', 'uid-1')
        self.assertEqual(again['status'], 'resent')
        self.assertEqual(again['scan']['id'], first['scan']['id'])
        # Un código sin producto no se desduplica por contenido: solo por uid.
        unknown = self.Scan.scanner_register(operator.id, 'ROB-RARO', 'uid-2')
        self.assertEqual(self.Scan.scanner_register(operator.id, 'ROB-RARO', 'uid-2')['status'], 'resent')
        self.assertEqual(self.Scan.search_count([('operator_id', '=', operator.id)]), 2)
        self.assertEqual(self.Scan.browse(unknown['scan']['id']).client_uid, 'uid-2')

    def test_resend_never_duplicates_batches(self):
        session = self._session()
        operator = self._operator(session)
        for source in (False, 'camera'):
            prefix = 'lote-%s' % (source or 'pda')
            codes = ['ROB-B1-%s' % prefix, 'ROB-B2-%s' % prefix]
            first = self.Scan.scanner_register_batch(operator.id, codes, prefix, source=source)
            again = self.Scan.scanner_register_batch(operator.id, codes, prefix, source=source)
            self.assertEqual([r['scan']['id'] for r in again['results']],
                             [r['scan']['id'] for r in first['results']])
            self.assertEqual({r['status'] for r in again['results']}, {'resent'})
        self.assertEqual(self.Scan.search_count([('operator_id', '=', operator.id)]), 4)

    def test_resend_never_duplicates_quantity(self):
        session = self._session()
        operator = self._operator(session)
        cable = self.env['product.product'].create({
            'name': 'ROB CABLE', 'is_storable': True, 'tracking': 'none', 'default_code': 'ROB-CABLE'})
        state = self.env.ref('rms_product_state.state_new')
        first = operator.scanner_qty_count(cable.id, 7, state.id, False, 'uid-qty')
        self.assertEqual(first['status'], 'ok')
        again = operator.scanner_qty_count(cable.id, 7, state.id, False, 'uid-qty')
        self.assertEqual(again['status'], 'resent')
        self.assertEqual(again['scan']['id'], first['scan']['id'])
        self.assertEqual(again['total'], 7)
        # También si el reenvío llega como "sumar": no suma otra vez.
        self.assertEqual(operator.scanner_qty_count(cable.id, 7, state.id, 'add', 'uid-qty')['total'], 7)

    def test_same_uid_at_the_same_time_is_retried_not_duplicated(self):
        """Dos peticiones a la vez con el mismo uid: el índice único frena la
        segunda y se pide a Odoo que repita la llamada (contestará 'resent')."""
        session = self._session()
        operator = self._operator(session)
        other = self._operator(session, 'Otro')
        self.Scan.scanner_register(operator.id, 'ROB-CARRERA', 'uid-carrera')
        vals = {'session_id': session.id, 'operator_id': operator.id, 'code': 'ROB-CARRERA',
                'scan_type': 'unknown', 'client_uid': 'uid-carrera'}
        with self.assertRaises(ConcurrencyError), mute_logger('odoo.sql_db'):
            self.Scan._create_scan(dict(vals))
        # El mismo uid en otro operario es otra lectura; sin uid no hay límite.
        self.assertTrue(self.Scan._create_scan(dict(vals, operator_id=other.id)))
        self.assertTrue(self.Scan._create_scan(dict(vals, client_uid=False)))
        self.assertTrue(self.Scan._create_scan(dict(vals, client_uid=False)))
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'), self.env.cr.savepoint():
            self.Scan.create(dict(vals))

    def test_missing_matches_the_site_marker_when_session_has_no_zone(self):
        for index in range(1, 6):
            self._line('01', 'ROB-FALTA-%02d' % index)
        self._line('02', 'ROB-FALTA-ET')
        self._line('01', 'ROB-FALTA-MAD', warehouse='AL1')   # otra nave: no cuenta
        session = self._session()
        self.assertFalse(session._sage_lines())               # recuento sin zona propia
        operator = self._operator(session)
        self.Scan.scanner_register(operator.id, 'ROB-FALTA-01', 'uid-f1')
        self.Scan.scanner_register(operator.id, 'ROB-FALTA-ET', 'uid-f2')
        progress = operator.scanner_progress()
        self.assertEqual((progress['total'], progress['pending']), (6, 4))
        missing = operator.scanner_finish()
        self.assertEqual(missing['scope'], 'site')
        self.assertEqual(missing['count'], progress['pending'])
        self.assertEqual(missing['site'], progress['site'])
        self.assertFalse(missing['truncated'])
        serials = sorted(serial for row in missing['missing'] for serial in row['serials'])
        self.assertEqual(serials, ['ROB-FALTA-%02d' % index for index in range(2, 6)])


# Los tests heredados de TestSageSites ya se ejecutan en su clase.
for _name in [name for name in dir(TestSageSites) if name.startswith("test_") and callable(getattr(TestSageSites, name))]:
    setattr(TestScannerRobustness, _name, None)
