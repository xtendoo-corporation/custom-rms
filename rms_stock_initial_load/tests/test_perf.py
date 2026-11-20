# -*- coding: utf-8 -*-
"""Tiempos con 3.000 líneas sintéticas (2.600 equipos con nº de serie + 400
artículos por cantidad). No entra en la pasada normal de tests:

    --test-tags rms_load_perf
"""
import logging
import time

from odoo.tests import tagged

from .common import COUNT_DAY, LoadCommon

_logger = logging.getLogger(__name__)


@tagged('post_install', '-at_install', '-standard', 'rms_load_perf')
class TestLoadPerf(LoadCommon):

    def test_three_thousand_lines(self):
        env = self.env
        products = env['product.product'].create([{
            'name': 'LOADPERF EQUIPO %03d' % index, 'default_code': 'LP-%03d' % index, 'categ_id': self.brand.id,
            'is_storable': True, 'tracking': 'serial', 'standard_price': 10 + index} for index in range(130)])
        cables = env['product.product'].create([{
            'name': 'LOADPERF CABLE %03d' % index, 'default_code': 'LPC-%03d' % index, 'categ_id': self.brand.id,
            'is_storable': True, 'tracking': 'none', 'standard_price': 2} for index in range(400)])
        wh7 = {code: env['rms.sage.warehouse'].search([('sage_company_code', '=', code), ('code', '=', 'A.7')]).id
               for code in ('01', '02', '03')}
        wh6 = env['rms.sage.warehouse'].search([('sage_company_code', '=', '01'), ('code', '=', 'A.6')]).id
        sage_vals, scan_vals = [], []
        new, demo = self.states['new'].id, self.states['demo'].id
        for index in range(2600):
            product = products[index % 130]
            code = ('01', '01', '02', '03')[index % 4]
            serial = 'LP%06d' % index
            kind = index % 20
            # 0-12 leído; 13-14 no leído (fantasma); 15-16 Mallorca; 17 depósito; 18 demo leído nuevo; 19 alta.
            if kind != 19:
                deposit = kind == 17
                sage_vals.append({
                    'snapshot_id': self._snapshot(code, 'stock').id, 'is_current': True,
                    'warehouse_code': 'A.6' if kind in (15, 16) else 'A.7',
                    'sage_warehouse_id': wh6 if kind in (15, 16) else wh7[code],
                    'article_code': product.default_code, 'model_code': product.default_code, 'serial': serial,
                    'quantity': 1, 'product_id': product.id, 'state': 'demo' if kind == 18 else 'nuevo',
                    'match_state': 'ok', 'in_deposit': deposit, 'cost': 50,
                    'partner_name': 'CLIENTE PERF %02d' % (index % 40) if deposit else False})
                if kind in (15, 16):
                    sage_vals[-1]['snapshot_id'] = self._snapshot('01', 'stock').id
            if kind <= 12 or kind >= 18:
                scan_vals.append({
                    'session_id': self.session.id, 'operator_id': self.operator.id, 'code': serial, 'raw_code': serial,
                    'scan_type': 'serial', 'product_id': product.id, 'lot_name': serial,
                    'product_state_id': new if kind != 18 else new, 'quantity': 1, 'scanned_at': COUNT_DAY})
        for index, cable in enumerate(cables):
            for code, quantity in (('01', 20), ('02', 6)):
                sage_vals.append({
                    'snapshot_id': self._snapshot(code, 'stock').id, 'is_current': True, 'warehouse_code': 'A.7',
                    'sage_warehouse_id': wh7[code], 'article_code': cable.default_code,
                    'model_code': cable.default_code, 'quantity': quantity, 'product_id': cable.id,
                    'state': 'nuevo', 'match_state': 'ok', 'cost': 1})
            if index % 4:
                scan_vals.append({
                    'session_id': self.session.id, 'operator_id': self.operator.id, 'code': cable.default_code,
                    'raw_code': cable.default_code, 'scan_type': 'product', 'product_id': cable.id,
                    'quantity': 22 + index % 7, 'scanned_at': COUNT_DAY})
        env['rms.sage.stock.line'].create(sage_vals)
        env['rms.stock.count.scan'].with_context(sage_batch=True).create(scan_vals)
        env.flush_all()
        _ = demo

        load = self.Load.create({'name': 'Carga de rendimiento', 'site_7': True})
        started = time.time()
        load.action_prepare()
        env.flush_all()
        prepare = time.time() - started
        lines = len(load.line_ids)
        entering = len(load.line_ids.filtered(lambda l: l.kind != 'skip'))
        self.assertGreaterEqual(entering, 3000)
        started = time.time()
        load.review_ids.action_use_sage()
        load.action_use_sage_cost()
        env.flush_all()
        review = time.time() - started
        started = time.time()
        load.action_apply()
        env.flush_all()
        apply = time.time() - started
        started = time.time()
        load._export_workbook()
        excel = time.time() - started
        started = time.time()
        load.action_undo()
        env.flush_all()
        undo = time.time() - started
        self.assertEqual(load.state, 'undone')
        _logger.info(
            'RMS_LOAD_PERF lineas=%d entran=%d revisiones=%d depositos_creados_y_borrados | preparar=%.1fs '
            'revisar+costes=%.1fs aplicar=%.1fs excel=%.1fs deshacer=%.1fs',
            lines, entering, len(load.review_ids), prepare, review, apply, excel, undo)
        # Sin tiempos absurdos: holgura amplia para una máquina lenta.
        self.assertLess(prepare, 120)
        self.assertLess(apply, 900)
