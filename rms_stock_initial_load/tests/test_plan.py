# -*- coding: utf-8 -*-
"""«Preparar» (simulación): reglas 1 a 9 de la carga de arranque."""
from datetime import date

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import AFTER, BEFORE, LoadCommon


@tagged('post_install', '-at_install')
class TestLoadPlan(LoadCommon):

    # ---- Reglas 1, 2, 3 y 4: contado, fantasma, no contado, empresa de Sage ----
    def test_counted_vs_uncounted_site(self):
        self.sage('01', self.product, 'LT-READ')
        self.sage('01', self.product, 'LT-LOST')
        self.sage('02', self.product, 'LT-ET-READ')
        self.sage('01', self.product, 'LT-MALLORCA', wh='A.6')
        self.scan('LT-READ', self.product, 'new')
        self.scan('LT-ET-READ', self.product, 'new')
        load = self.new_load()
        self.assertEqual(load.state, 'prepared')
        read = self.line(load, 'LT-READ')
        self.assertEqual((read.kind, read.location_id, read.company_id, read.unverified),
                         ('counted', self.wh['RMS7'].lot_stock_id, self.c1, False))
        lost = self.line(load, 'LT-LOST')
        self.assertEqual((lost.kind, lost.company_id, lost.site_number), ('phantom', self.c1, 7))
        self.assertFalse(lost.location_id, 'la ubicación fantasma se crea al aplicar')
        other = self.line(load, 'LT-ET-READ')
        self.assertEqual((other.kind, other.location_id, other.company_id),
                         ('counted', self.wh['ET7'].lot_stock_id, self.c2))
        mallorca = self.line(load, 'LT-MALLORCA')
        self.assertEqual((mallorca.kind, mallorca.location_id, mallorca.unverified),
                         ('sage_unverified', self.wh['RMS6'].lot_stock_id, True))
        # Preparar no toca el stock.
        self.assertFalse(self.env['stock.lot'].search([('product_id', '=', self.product.id)]))
        self.assertEqual(self.stock(self.product), 0)
        self.assertIn('Sevilla', load.summary_html)

    def test_prepare_can_be_repeated_and_recalculates(self):
        self.sage('01', self.product, 'LT-A')
        self.scan('LT-OTHER', self.product2, 'new')
        load = self.new_load()
        self.assertEqual(self.line(load, 'LT-A').kind, 'phantom')
        self.line(load, 'LT-A').cost = 55
        self.scan('LT-A', self.product, 'new')
        load.action_prepare()
        line = self.line(load, 'LT-A')
        self.assertEqual(len(line), 1)
        self.assertEqual(line.kind, 'counted')

    def test_counted_site_without_scans_is_refused(self):
        self.sage('01', self.product, 'LT-A', wh='A.6')
        with self.assertRaises(UserError):
            self.new_load(sites=(6,))

    def test_read_in_another_site_than_sage(self):
        """Manda lo contado: Sage lo tiene en Mallorca y se leyó en Sevilla."""
        self.sage('02', self.product, 'LT-MOVED', wh='A.6')
        self.scan('LT-MOVED', self.product, 'new')
        line = self.line(self.new_load(), 'LT-MOVED')
        self.assertEqual((line.kind, line.location_id), ('counted', self.wh['ET7'].lot_stock_id))

    # ---- Regla 4: altas ----
    def test_alta_goes_to_rms(self):
        self.scan('LT-ALTA', self.product, 'second_hand')
        self.scan('LT-UNKNOWN', scan_type='unknown')
        load = self.new_load()
        alta = self.line(load, 'LT-ALTA')
        self.assertEqual((alta.kind, alta.company_id, alta.location_id, alta.state_id.code),
                         ('alta', self.c1, self.wh['RMS7'].lot_stock_id, 'second_hand'))
        self.assertFalse(alta.cost)
        self.assertTrue(alta.cost_pending)
        unknown = self.env['rms.initial.load.line'].search([('load_id', '=', load.id), ('kind', '=', 'skip')])
        self.assertEqual(len(unknown), 1)
        self.assertIn('sin identificar', unknown.note)

    # ---- Regla 5: estados ----
    def test_sage_demo_enters_as_demo_never_ex_demo(self):
        self.sage('01', self.product, 'LT-D-UNREAD', wh='A.6', state='demo')
        self.sage('01', self.product, 'LT-2M-UNREAD', wh='A.6', state='2mano')
        self.sage('01', self.product, 'LT-D-READ', state='demo')
        self.sage('01', self.product, 'LT-D-NOSTATE', state='demo')
        self.scan('LT-D-READ', self.product, 'demo')
        self.scan('LT-D-NOSTATE', self.product)
        load = self.new_load()
        self.assertEqual(self.line(load, 'LT-D-UNREAD').state_id.code, 'demo')
        self.assertEqual(self.line(load, 'LT-2M-UNREAD').state_id.code, 'second_hand')
        self.assertEqual(self.line(load, 'LT-D-READ').state_id.code, 'demo')
        self.assertEqual(self.line(load, 'LT-D-NOSTATE').state_id.code, 'demo')
        self.assertFalse(load.review_ids)

    def test_state_mismatch_creates_review_and_blocks_apply(self):
        self.sage('01', self.product, 'LT-S1', state='demo')
        self.sage('01', self.product, 'LT-S2', state='demo')
        self.sage('01', self.product, 'LT-S3', state='nuevo')
        self.scan('LT-S1', self.product, 'new')
        self.scan('LT-S2', self.product, 'ex_demo')
        self.scan('LT-S3', self.product, 'new')
        load = self.new_load()
        self.assertEqual(sorted(load.review_ids.mapped('serial')), ['LT-S1', 'LT-S2'])
        self.assertEqual(load.review_pending_count, 2)
        review1 = load.review_ids.filtered(lambda r: r.serial == 'LT-S1')
        self.assertEqual((review1.sage_state, review1.scanned_state_id.code, review1.site_number, review1.session_id),
                         ('demo', 'new', 7, self.session))
        with self.assertRaises(UserError):
            load.action_apply()
        review1.action_use_sage()
        self.assertEqual((review1.state, review1.final_state_id.code, review1.reviewed_by), ('done', 'demo', self.env.user))
        self.assertTrue(review1.reviewed_on)
        self.assertEqual(self.line(load, 'LT-S1').state_id.code, 'demo')
        with self.assertRaises(UserError):
            load.action_apply()  # queda LT-S2
        review2 = load.review_ids.filtered(lambda r: r.serial == 'LT-S2')
        review2.action_set_ex_demo()
        self.assertEqual(self.line(load, 'LT-S2').state_id.code, 'ex_demo')
        # Volver a preparar conserva lo ya revisado.
        load.action_prepare()
        self.assertEqual(load.review_pending_count, 0)
        self.assertEqual(self.line(load, 'LT-S1').state_id.code, 'demo')
        self.assertEqual(self.line(load, 'LT-S2').state_id.code, 'ex_demo')
        load.action_apply()
        self.assertEqual(self.lot('LT-S1').product_state_id.code, 'demo')
        self.assertEqual(self.lot('LT-S2').product_state_id.code, 'ex_demo')
        self.assertEqual(self.lot('LT-S3').product_state_id.code, 'new')

    # ---- Regla 6: depósitos ----
    def test_inherited_deposits_by_partner(self):
        partner = self.env['res.partner'].create({'name': 'Sonido Sur Loadtest, S.L.', 'is_company': True})
        self.sage_deposit('01', self.product, 'LT-DEP1', 'SONIDO SUR LOADTEST SL')
        self.sage_deposit('01', self.product, 'LT-DEP2', 'Sonido Sur Loadtest S.L.')
        self.sage_deposit('01', self.product, 'LT-DEP3', 'CLIENTE QUE NO EXISTE LOADTEST')
        self.sage_deposit('02', self.product, 'LT-DEP4', 'SONIDO SUR LOADTEST SL', state='demo')
        self.sage_deposit('01', self.product, 'LT-DEP-READ', 'SONIDO SUR LOADTEST SL')
        self.sage_move('LT-DEP1', 'deposit', move_date=date(2026, 3, 14), partner='SONIDO SUR LOADTEST SL')
        self.scan('LT-DEP-READ', self.product, 'new')
        load = self.new_load()
        generic = self.env.ref('rms_stock_initial_load.partner_inherited_deposits')
        dep1 = self.line(load, 'LT-DEP1')
        self.assertEqual((dep1.kind, dep1.partner_id, dep1.deposit_date, dep1.unverified),
                         ('deposit', partner, date(2026, 3, 14), True))
        dep3 = self.line(load, 'LT-DEP3')
        self.assertEqual((dep3.kind, dep3.partner_id, dep3.sage_partner_name),
                         ('deposit', generic, 'CLIENTE QUE NO EXISTE LOADTEST'))
        # Leído en la nave estando en depósito: manda lo contado.
        read = self.line(load, 'LT-DEP-READ')
        self.assertEqual((read.kind, read.location_id, read.deposit_to_close),
                         ('counted', self.wh['RMS7'].lot_stock_id, True))
        self.assertIn('DEPÓSITO A CERRAR EN SAGE', read.note)
        partners_before = self.env['res.partner'].search_count([])
        load.action_apply()
        self.assertEqual(self.env['res.partner'].search_count([]), partners_before, 'no se crean clientes')
        cessions = load.cession_ids
        self.assertEqual(len(cessions), 3, 'uno por cliente y empresa')
        mine = cessions.filtered(lambda c: c.partner_id == partner and c.company_id == self.c1)
        self.assertEqual(len(mine), 1)
        self.assertTrue(mine.rms_inherited_from_sage)
        self.assertEqual(mine.state, 'done')
        self.assertEqual(mine.rms_deposit_state, 'out')
        self.assertEqual(sorted(mine.rms_unit_ids.mapped('lot_id.name')), ['LT-DEP1', 'LT-DEP2'])
        self.assertEqual(mine.date.date(), date(2026, 3, 14))
        self.assertEqual(mine.rms_unit_ids.filtered(lambda u: u.lot_id.name == 'LT-DEP1').date_out.date(),
                         date(2026, 3, 14))
        other_company = cessions.filtered(lambda c: c.company_id == self.c2)
        self.assertEqual((other_company.partner_id, other_company.rms_unit_ids.lot_id.product_state_id.code),
                         (partner, 'demo'))
        orphan = cessions.filtered(lambda c: c.partner_id == generic)
        self.assertEqual(orphan.rms_sage_partner_name, 'CLIENTE QUE NO EXISTE LOADTEST')
        deposit_location = self.env['stock.cession']._rms_deposit_location(self.c1)
        self.assertEqual(self.stock(self.product, deposit_location), 3)
        self.assertEqual(self.stock(self.product, self.wh['RMS7'].lot_stock_id, lot='LT-DEP-READ'), 1)
        self.assertTrue(self.lot('LT-DEP1').rms_unverified)
        self.assertNotIn('LT-DEP-READ', cessions.rms_unit_ids.mapped('lot_id.name'))

    # ---- Regla 7: por cantidad ----
    def test_quantity_split_between_companies(self):
        for product in (self.cable, self.cable2, self.cable3):
            self.sage('01', product, None, qty=10, cost=2.0)
            self.sage('02', product, None, qty=5)
            self.sage('03', product, None, qty=3)
        self.sage('01', self.cable, None, qty=7, wh='A.6')
        self.count_qty(self.cable, 12)
        self.count_qty(self.cable, 8)       # sobrante: 20 contados, Sage 18
        self.count_qty(self.cable2, 12)     # falta: 12 contados, Sage 18
        load = self.new_load()

        def qty(product, kind, company, site=7):
            return sum(self.line(load, product=product, kind=kind, company_id=company.id, site_number=site)
                       .mapped('quantity'))
        # Sobrante a RMS.
        self.assertEqual(qty(self.cable, 'qty_counted', self.c1), 12)
        self.assertEqual(qty(self.cable, 'qty_counted', self.c2), 5)
        self.assertEqual(qty(self.cable, 'qty_counted', self.c3), 3)
        self.assertFalse(self.line(load, product=self.cable, kind='phantom'))
        # Falta: al fantasma de la empresa a la que le falta.
        self.assertEqual(qty(self.cable2, 'qty_counted', self.c1), 10)
        self.assertEqual(qty(self.cable2, 'qty_counted', self.c2), 2)
        self.assertEqual(qty(self.cable2, 'qty_counted', self.c3), 0)
        self.assertEqual(qty(self.cable2, 'phantom', self.c2), 3)
        self.assertEqual(qty(self.cable2, 'phantom', self.c3), 3)
        self.assertEqual(qty(self.cable2, 'phantom', self.c1), 0)
        # Nadie lo contó en la nave contada: cantidad de Sage sin verificar.
        self.assertEqual(qty(self.cable3, 'qty_sage', self.c1), 10)
        self.assertEqual(qty(self.cable3, 'qty_sage', self.c3), 3)
        self.assertTrue(all(self.line(load, product=self.cable3).mapped('unverified')))
        self.assertFalse(any(self.line(load, product=self.cable, kind='qty_counted').mapped('unverified')))
        # Nave no contada: cantidad de Sage sin verificar.
        mallorca = self.line(load, product=self.cable, site_number=6)
        self.assertEqual((mallorca.kind, mallorca.quantity, mallorca.unverified, mallorca.location_id),
                         ('qty_sage', 7, True, self.wh['RMS6'].lot_stock_id))
        load.action_apply()
        self.assertEqual(self.stock(self.cable, self.wh['RMS7'].lot_stock_id), 12)
        self.assertEqual(self.stock(self.cable, self.wh['ET7'].lot_stock_id), 5)
        self.assertEqual(self.stock(self.cable, self.wh['RJB7'].lot_stock_id), 3)
        self.assertEqual(self.stock(self.cable, self.wh['RMS6'].lot_stock_id), 7)
        self.assertEqual(self.stock(self.cable2, self.wh['ET7'].lot_stock_id), 2)
        phantom = self.env['stock.location']._rms_phantom_location(self.c2, create=False)
        self.assertEqual(self.stock(self.cable2, phantom), 3)
        self.assertEqual(self.stock(self.cable2, self.wh['RJB7'].lot_stock_id), 0)

    # ---- Regla 8: movimientos de Sage posteriores al recuento ----
    def test_sage_moves_after_count(self):
        for serial in ('LT-SOLD', 'LT-TO-DEP', 'LT-BOUGHT', 'LT-BACK', 'LT-TRANSFER', 'LT-OLD-MOVE', 'LT-NOTHING'):
            self.sage('01', self.product, serial)
        self.scan('LT-SOLD', self.product, 'new')
        self.scan('LT-TO-DEP', self.product, 'new')
        self.scan('LT-TRANSFER', self.product, 'new')
        sold = self.sage_move('LT-SOLD', 'sale', partner='CLIENTE FINAL')
        deposit = self.sage_move('LT-TO-DEP', 'deposit', partner='CLIENTE DEPOSITO LOADTEST')
        self.sage_move('LT-BOUGHT', 'purchase', partner='PROVEEDOR')
        self.sage_move('LT-BACK', 'deposit_return', partner='CLIENTE')
        self.sage_move('LT-TRANSFER', 'transfer', wh_from='A.7', wh_to='AL1')
        self.sage_move('LT-OLD-MOVE', 'purchase', move_date=BEFORE)
        load = self.new_load()
        line = self.line(load, 'LT-SOLD')
        self.assertEqual((line.kind, line.sage_move_id), ('skip', sold))
        self.assertIn('vendido', line.note)
        line = self.line(load, 'LT-TO-DEP')
        self.assertEqual((line.kind, line.sage_move_id, line.sage_partner_name, line.deposit_date),
                         ('deposit', deposit, 'CLIENTE DEPOSITO LOADTEST', AFTER))
        for serial in ('LT-BOUGHT', 'LT-BACK'):
            line = self.line(load, serial)
            self.assertEqual((line.kind, line.location_id, line.unverified),
                             ('sage_unverified', self.wh['RMS7'].lot_stock_id, True), serial)
            self.assertTrue(line.sage_move_id)
        line = self.line(load, 'LT-TRANSFER')
        self.assertEqual((line.kind, line.location_id, line.unverified, line.site_number),
                         ('sage_unverified', self.wh['RMS1'].lot_stock_id, True, 1))
        # Un movimiento anterior al recuento no cuenta: no leído -> fantasma.
        self.assertEqual(self.line(load, 'LT-OLD-MOVE').kind, 'phantom')
        self.assertEqual(self.line(load, 'LT-NOTHING').kind, 'phantom')
        load.action_apply()
        self.assertFalse(self.lot('LT-SOLD'))
        self.assertEqual(self.stock(self.product, self.wh['RMS1'].lot_stock_id, lot='LT-TRANSFER'), 1)
        self.assertEqual(load.cession_ids.rms_unit_ids.lot_id.name, 'LT-TO-DEP')

    # ---- Regla 9: almacenes de Sage sin nave ----
    def test_sage_warehouse_without_site_is_not_loaded(self):
        self.sage('01', self.product, 'LT-RA', wh='AL8')
        self.sage('01', self.cable, None, qty=4, wh='AL8')
        self.sage('01', None, 'LT-NOPROD')
        self.scan('LT-X', self.product2, 'new')
        load = self.new_load()
        line = self.line(load, 'LT-RA')
        self.assertEqual(line.kind, 'skip')
        self.assertIn('sin ubicar, no cargado', line.note)
        cable = self.line(load, product=self.cable)
        self.assertEqual((cable.kind, cable.quantity), ('skip', 4))
        self.assertEqual(self.line(load, 'LT-NOPROD').kind, 'skip')
        load.action_apply()
        self.assertFalse(self.lot('LT-RA'))
        self.assertEqual(self.stock(self.cable), 0)

    # ---- "SN" delante en Sage (AtlasIED) ----
    def test_sn_prefix_in_sage_matches_scan(self):
        self.sage('01', self.product, 'SN0077001')
        self.sage('01', self.product, '88002')
        self.scan('77001', self.product, 'new')
        self.scan('SN88002', self.product, 'new')
        load = self.new_load()
        lines = self.env['rms.initial.load.line'].search([('load_id', '=', load.id)])
        self.assertEqual(sorted(lines.mapped('kind')), ['counted', 'counted'])
        self.assertEqual(sorted(lines.mapped('lot_name')), ['77001', 'SN88002'], 'entra con lo que dice la etiqueta')

    def test_confirmed_probable_match_pairs_with_sage_unit(self):
        """Caso real FC-8ST: Sage tiene el nº de serie con un "4" de más. Con la
        coincidencia confirmada en el escáner, entra UNA unidad con el nº de la
        etiqueta: ni alta, ni la línea de Sage a «Pendiente de localizar»."""
        self.sage('01', self.product, 'DQ7031901524040014')
        scan = self.scan('DQ703190152400014', self.product, 'new')
        load = self.new_load()
        self.assertEqual(sorted(load.line_ids.mapped('kind')), ['alta', 'phantom'], 'sin emparejar: alta + fantasma')
        scan.write({'sage_match_state': 'confirmed', 'sage_match_key': 'DQ7031901524040014'})
        load.action_prepare()
        lines = self.env['rms.initial.load.line'].search([('load_id', '=', load.id)])
        self.assertEqual(lines.mapped('kind'), ['counted'])
        self.assertEqual(lines.lot_name, 'DQ703190152400014', 'entra con lo que dice la etiqueta')

    def test_sage_duplicate_serial_is_loaded_once(self):
        self.sage('01', self.product, 'LT-DUP', wh='A.6')
        self.sage('02', self.product, 'LT-DUP', wh='A.6')
        self.scan('LT-Z', self.product2, 'new')
        load = self.new_load()
        lines = self.line(load, 'LT-DUP')
        self.assertEqual(sorted(lines.mapped('kind')), ['sage_unverified', 'skip'])
        load.action_apply()
        self.assertEqual(self.stock(self.product, lot='LT-DUP'), 1)

    # ---- Depósitos: el cliente sale de los movimientos de Sage si la línea no lo trae ----
    def test_deposit_partner_from_sage_moves(self):
        partner = self.env['res.partner'].create({'name': 'Alquileres Loadtest Norte, S.L.', 'is_company': True})
        for serial in ('LT-DM-OLD', 'SN0055001', 'LT-DM-RETURNED', 'LT-DM-SOLD', 'LT-DM-NONE', 'LT-DM-REOPEN'):
            self.sage_deposit('01', self.product, serial, None)
        # Depósito antiguo (muy anterior al recuento) y sin vuelta: vale.
        self.sage_move('LT-DM-OLD', 'deposit', move_date=date(2025, 6, 3), partner='ALQUILERES LOADTEST NORTE SL')
        # Sage guarda "SN" delante y el movimiento no.
        self.sage_move('55001', 'deposit', move_date=date(2026, 1, 20), partner='ALQUILERES LOADTEST NORTE SL')
        # Con vuelta de depósito o venta posterior, ese depósito ya no vale.
        self.sage_move('LT-DM-RETURNED', 'deposit', move_date=date(2026, 2, 1), partner='ALQUILERES LOADTEST NORTE SL')
        self.sage_move('LT-DM-RETURNED', 'deposit_return', move_date=date(2026, 4, 1), partner='ALQUILERES LOADTEST NORTE SL')
        self.sage_move('LT-DM-SOLD', 'deposit', move_date=date(2026, 2, 1), partner='ALQUILERES LOADTEST NORTE SL')
        self.sage_move('LT-DM-SOLD', 'sale', move_date=date(2026, 5, 1), partner='OTRO CLIENTE')
        # Devuelto y vuelto a dejar: manda el último depósito.
        self.sage_move('LT-DM-REOPEN', 'deposit', move_date=date(2026, 2, 1), partner='CLIENTE VIEJO LOADTEST')
        self.sage_move('LT-DM-REOPEN', 'deposit_return', move_date=date(2026, 3, 1), partner='CLIENTE VIEJO LOADTEST')
        self.sage_move('LT-DM-REOPEN', 'deposit', move_date=date(2026, 6, 1), partner='ALQUILERES LOADTEST NORTE SL')
        self.scan('LT-Q', self.product2, 'new')
        load = self.new_load()
        generic = self.env.ref('rms_stock_initial_load.partner_inherited_deposits')
        expected = {'LT-DM-OLD': date(2025, 6, 3), 'SN0055001': date(2026, 1, 20), 'LT-DM-REOPEN': date(2026, 6, 1)}
        for serial, day in expected.items():
            line = self.line(load, serial)
            self.assertEqual((line.kind, line.partner_id, line.sage_partner_name, line.deposit_date),
                             ('deposit', partner, 'ALQUILERES LOADTEST NORTE SL', day), serial)
            self.assertFalse(line.sage_move_id, 'no es un movimiento posterior al recuento')
        for serial in ('LT-DM-RETURNED', 'LT-DM-SOLD', 'LT-DM-NONE'):
            line = self.line(load, serial)
            self.assertEqual((line.kind, line.partner_id, line.sage_partner_name, line.deposit_date),
                             ('deposit', generic, '(sin nombre en Sage)', load.date), serial)
        self.assertIn(('Depósitos heredados sin cliente identificado (equipos)', 3.0), load._extra_figures())
        self.assertIn('Depósitos heredados sin cliente identificado', load.summary_html)
        from openpyxl import load_workbook
        import io
        book = load_workbook(io.BytesIO(load._export_workbook()))
        self.assertEqual(sorted(row[6].value for row in book['Depósitos sin cliente'].iter_rows(min_row=2)),
                         ['LT-DM-NONE', 'LT-DM-RETURNED', 'LT-DM-SOLD'])
        load.action_apply()
        named = load.cession_ids.filtered(lambda c: c.partner_id == partner)
        self.assertEqual(sorted(named.rms_unit_ids.mapped('lot_id.name')), ['LT-DM-OLD', 'LT-DM-REOPEN', 'SN0055001'])
        self.assertEqual(named.date.date(), date(2025, 6, 3))
        self.assertEqual(len(load.cession_ids.filtered(lambda c: c.partner_id == generic).rms_unit_ids), 3)
