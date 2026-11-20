# -*- coding: utf-8 -*-
"""«Aplicar» y «Deshacer»: existencias, fantasma, altas, multiempresa, costes."""
import base64
import io

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import LoadCommon


@tagged('post_install', '-at_install')
class TestLoadApply(LoadCommon):

    def _basic(self):
        self.product.standard_price = 100.0
        self.sage('01', self.product, 'LT-READ', cost=80.0)
        self.sage('01', self.product, 'LT-LOST', cost=80.0)
        self.sage('02', self.product, 'LT-ET', state='2mano')
        self.sage('01', self.product, 'LT-MALLORCA', wh='A.6', state='demo')
        self.scan('LT-READ', self.product, 'new')
        self.scan('LT-ET', self.product, 'second_hand')
        self.scan('LT-ALTA', self.product, 'ex_demo')
        return self.new_load()

    # ---- Aplicar: nº de serie con su estado, en su nave y su empresa ----
    def test_apply_creates_lots_with_state_and_stock(self):
        load = self._basic()
        load.action_apply()
        self.assertEqual(load.state, 'applied')
        expected = {
            'LT-READ': ('new', self.wh['RMS7'].lot_stock_id, False, False),
            'LT-ET': ('second_hand', self.wh['ET7'].lot_stock_id, False, False),
            'LT-MALLORCA': ('demo', self.wh['RMS6'].lot_stock_id, True, False),
            'LT-ALTA': ('ex_demo', self.wh['RMS7'].lot_stock_id, False, True),
        }
        for serial, (state, location, unverified, alta) in expected.items():
            lot = self.lot(serial)
            self.assertEqual(len(lot), 1, serial)
            self.assertEqual((lot.product_state_id.code, lot.rms_unverified, lot.rms_alta_review, lot.rms_initial_load_id),
                             (state, unverified, alta, load), serial)
            quant = self.env['stock.quant'].search([('lot_id', '=', lot.id), ('quantity', '>', 0)])
            self.assertEqual((quant.location_id, quant.quantity, quant.company_id),
                             (location, 1, location.company_id), serial)
            # El estado también queda en la línea del movimiento (rms_product_state lo copia al validar).
            line = self.line(load, serial)
            self.assertEqual(line.apply_result, 'done')
            self.assertEqual(line.move_id.state, 'done')
            self.assertTrue(line.move_id.is_inventory)
            self.assertEqual(line.move_id.move_line_ids.product_state_id.code, state)
            self.assertEqual(line.lot_id, lot)
        # Multiempresa: cada existencia en la empresa de Sage.
        self.assertEqual(self.lot('LT-ET').location_id.company_id, self.c2)
        self.assertEqual(self.line(load, 'LT-ET').move_id.company_id, self.c2)
        # No se puede aplicar dos veces.
        with self.assertRaises(UserError):
            load.action_apply()
        self.assertEqual(self.stock(self.product), 5)

    def test_apply_needs_the_three_companies_and_a_manager(self):
        load = self._basic()
        with self.assertRaises(UserError):
            load.with_context(allowed_company_ids=[self.c1.id]).action_apply()
        user = self.env['res.users'].create({
            'name': 'Operario carga', 'login': 'loadtest_operario',
            'group_ids': [(6, 0, [self.env.ref('stock.group_stock_user').id])]})
        with self.assertRaises(AccessError):
            load.with_user(user).action_apply()
        self.assertEqual(load.state, 'prepared')

    # ---- Regla 1: el fantasma no se reserva y no valora ----
    def test_phantom_is_not_reservable_and_has_no_value(self):
        load = self._basic()
        load.action_apply()
        phantom = self.env['stock.location']._rms_phantom_location(self.c1, create=False)
        self.assertTrue(phantom)
        self.assertEqual((phantom.usage, phantom.company_id), ('inventory', self.c1))
        self.assertFalse(phantom._should_be_valued())
        self.assertFalse(phantom.warehouse_id, 'no cuelga de ningún almacén')
        self.assertEqual(self.stock(self.product, phantom, lot='LT-LOST'), 1)
        lost = self.line(load, 'LT-LOST')
        read = self.line(load, 'LT-READ')
        # Valoración: el movimiento al fantasma vale 0; el de la nave, el coste del producto.
        self.assertEqual(lost.move_id.value, 0)
        self.assertFalse(lost.move_id.is_in)
        self.assertTrue(read.move_id.is_in)
        self.assertEqual(read.move_id.value, 100.0)
        product = self.product.with_company(self.c1).with_context(allowed_company_ids=[self.c1.id])
        product.invalidate_recordset()
        # RMS: LT-READ + LT-ALTA en Sevilla y LT-MALLORCA; el fantasma no cuenta ni en cantidad ni en valor.
        self.assertEqual(product.qty_available, 3)
        self.assertEqual(product.total_value, 300.0)
        self.assertEqual(self.lot('LT-LOST').with_company(self.c1).product_qty, 0)
        # No se puede reservar: un albarán de salida que pide 3 en Sevilla solo encuentra las 2 de la nave.
        warehouse = self.wh['RMS7']
        customers = self.env.ref('stock.stock_location_customers')
        picking = self.env['stock.picking'].create({
            'picking_type_id': warehouse.out_type_id.id, 'location_id': warehouse.lot_stock_id.id,
            'location_dest_id': customers.id, 'company_id': self.c1.id,
            'move_ids': [(0, 0, {
                'product_id': self.product.id, 'product_uom_qty': 3, 'product_uom': self.product.uom_id.id,
                'location_id': warehouse.lot_stock_id.id, 'location_dest_id': customers.id,
                'company_id': self.c1.id})]})
        picking.action_confirm()
        picking.action_assign()
        reserved = picking.move_ids.move_line_ids.lot_id.mapped('name')
        self.assertEqual(sorted(reserved), ['LT-ALTA', 'LT-READ'])
        self.assertNotIn('LT-LOST', reserved)
        self.assertEqual(picking.move_ids.state, 'partially_available')
        # Tampoco desde una venta.
        partner = self.env['res.partner'].create({'name': 'Cliente venta loadtest'})
        order = self.env['sale.order'].with_company(self.c1).create({
            'partner_id': partner.id, 'warehouse_id': self.wh['RMS6'].id,
            'order_line': [(0, 0, {'product_id': self.product.id, 'product_uom_qty': 2, 'price_unit': 10})]})
        order.action_confirm()
        order.picking_ids.action_assign()
        sale_reserved = order.picking_ids.move_ids.move_line_ids.lot_id.mapped('name')
        self.assertEqual(sale_reserved, ['LT-MALLORCA'])

    # ---- Regla 4: altas por revisar ----
    def test_alta_review_and_change_company(self):
        load = self._basic()
        load.action_apply()
        lot = self.lot('LT-ALTA')
        self.assertIn(lot, self.env['stock.lot'].search([('rms_alta_review', '=', True)]))
        self.assertEqual(lot.rms_stock_company_id, self.c1)
        wizard = self.env['rms.initial.load.alta.company'].create({'lot_id': lot.id, 'company_id': self.c2.id})
        self.assertEqual(wizard.location_id, self.wh['ET7'].lot_stock_id, 'misma nave, otra empresa')
        wizard.action_apply()
        self.assertEqual(self.stock(self.product, self.wh['RMS7'].lot_stock_id, lot='LT-ALTA'), 0)
        self.assertEqual(self.stock(self.product, self.wh['ET7'].lot_stock_id, lot='LT-ALTA'), 1)
        self.assertFalse(lot.rms_alta_review)
        self.assertEqual(lot.product_state_id.code, 'ex_demo')
        other = self.lot('LT-MALLORCA')
        other.action_rms_mark_verified()
        self.assertFalse(other.rms_unverified)

    # ---- Aplicar + Deshacer ----
    def test_undo_leaves_no_stock(self):
        self.sage_deposit('01', self.product, 'LT-DEP', 'CLIENTE LOADTEST UNDO')
        self.sage('01', self.cable, None, qty=6)
        self.count_qty(self.cable, 4)
        load = self._basic()
        load.action_apply()
        self.assertEqual(self.stock(self.product), 6)
        self.assertEqual(self.stock(self.cable), 6)
        self.assertEqual(len(load.cession_ids), 1)
        load.action_undo()
        self.assertEqual(load.state, 'undone')
        self.assertEqual(self.stock(self.product), 0)
        self.assertEqual(self.stock(self.cable), 0)
        quants = self.env['stock.quant'].sudo().search([
            ('product_id', 'in', (self.product | self.cable).ids), ('quantity', '!=', 0),
            ('location_id.usage', 'in', ('internal', 'transit'))])
        self.assertFalse(quants)
        self.assertFalse(self.env['stock.quant'].sudo().search([
            ('location_id.rms_phantom', '=', True), ('quantity', '!=', 0),
            ('product_id', 'in', (self.product | self.cable).ids)]))
        self.assertFalse(load.cession_ids)
        self.assertFalse(self.env['stock.cession'].search([('rms_initial_load_id', '=', load.id)]))
        lots = self.env['stock.lot'].search([('product_id', '=', self.product.id)])
        self.assertFalse(any(lots.mapped('rms_unverified')) or any(lots.mapped('rms_alta_review')))
        self.assertEqual(set(load.line_ids.filtered('move_id').mapped('apply_result')), {'undone'})
        product = self.product.with_company(self.c1).with_context(allowed_company_ids=[self.c1.id])
        product.invalidate_recordset()
        self.assertEqual(product.total_value, 0)
        with self.assertRaises(UserError):
            load.action_undo()
        # Se puede volver a preparar y aplicar (ensayo): reutiliza los nº de serie.
        load.action_prepare()
        load.action_apply()
        self.assertEqual(self.stock(self.product), 6)
        self.assertEqual(len(self.lot('LT-READ')), 1)

    def test_undo_refused_when_stock_already_moved(self):
        load = self._basic()
        load.action_apply()
        lot = self.lot('LT-READ')
        scrap_location = self.env['stock.location'].search(
            [('usage', '=', 'inventory'), ('company_id', '=', self.c1.id), ('rms_phantom', '=', False)], limit=1)
        move = self.env['stock.move'].create(self.Load._rms_move_vals(
            self.c1, self.product, 1, self.wh['RMS7'].lot_stock_id, scrap_location, lot=lot, name='salida'))
        move._action_done()
        with self.assertRaises(UserError):
            load.action_undo()
        self.assertEqual(load.state, 'applied')

    # ---- No duplicar un nº de serie que ya tiene stock ----
    def test_existing_serial_with_stock_is_not_duplicated(self):
        lot = self.env['stock.lot'].create({'name': 'LT-READ', 'product_id': self.product.id})
        empty = self.env['stock.lot'].create({'name': 'LT-ET', 'product_id': self.product.id})
        self.env['stock.quant']._update_available_quantity(self.product, self.wh['RMS1'].lot_stock_id, 1, lot_id=lot)
        load = self._basic()
        load.action_apply()
        line = self.line(load, 'LT-READ')
        self.assertEqual(line.apply_result, 'duplicate')
        self.assertFalse(line.move_id)
        self.assertIn('YA TENÍA EXISTENCIAS', line.note)
        self.assertEqual(self.stock(self.product, lot='LT-READ'), 1)
        self.assertEqual(self.stock(self.product, self.wh['RMS1'].lot_stock_id, lot='LT-READ'), 1)
        self.assertEqual(load.duplicate_count, 1)
        self.assertFalse(lot.rms_initial_load_id)
        # Un nº de serie que existe sin existencias se reutiliza (con el estado de la carga).
        self.assertEqual(self.line(load, 'LT-ET').lot_id, empty)
        self.assertEqual(empty.product_state_id.code, 'second_hand')
        self.assertEqual(self.stock(self.product, lot='LT-ET'), 1)
        load.action_undo()
        self.assertEqual(self.stock(self.product, lot='LT-READ'), 1, 'lo que ya estaba no se toca')

    # ---- Regla 10: costes ----
    def _cost_excel(self, rows):
        from openpyxl import Workbook
        book = Workbook()
        sheet = book.active
        sheet.append(['Artículo', 'Estado', 'Coste'])
        for row in rows:
            sheet.append(row)
        stream = io.BytesIO()
        book.save(stream)
        return base64.b64encode(stream.getvalue())

    def test_costs_are_optional_and_counted(self):
        self.sage('01', self.cable, None, qty=6, cost=1.5)
        self.count_qty(self.cable, 6)
        load = self._basic()
        self.assertEqual(load.no_cost_units, 10, '4 equipos + 6 cables; el fantasma no cuenta')
        load.action_use_sage_cost()
        self.assertEqual(self.line(load, 'LT-READ').cost, 80.0)
        self.assertEqual(self.line(load, product=self.cable).cost, 1.5)
        self.assertEqual(load.no_cost_units, 3)
        wizard = self.env['rms.initial.load.cost.import'].create({
            'load_id': load.id, 'filename': 'costes.xlsx',
            'file': self._cost_excel([['LT-ALT', '', 60], ['lt alt', 'Demo', '45,50'], ['NO-EXISTE', '', 9]])})
        wizard.action_import()
        self.assertIn('NO-EXISTE', wizard.result)
        self.assertEqual(self.line(load, 'LT-READ').cost, 60)
        self.assertEqual(self.line(load, 'LT-ALTA').cost, 60)
        self.assertEqual(self.line(load, 'LT-MALLORCA').cost, 45.5)
        self.assertEqual(load.no_cost_units, 0)
        # Volver a preparar conserva los costes.
        load.action_prepare()
        self.assertEqual(self.line(load, 'LT-MALLORCA').cost, 45.5)
        self.line(load, 'LT-ET').cost = 0
        self.assertEqual(load.no_cost_units, 1)
        load.action_apply()  # el coste vacío no bloquea
        self.assertEqual(self.line(load, 'LT-READ').move_id.value, 60)
        self.assertEqual(self.line(load, 'LT-MALLORCA').move_id.value, 45.5)
        self.assertEqual(self.line(load, 'LT-LOST').move_id.value, 0)
        with self.assertRaises(UserError):
            self.line(load, 'LT-READ').cost = 1

    def test_excel_export(self):
        from openpyxl import load_workbook
        self.sage_deposit('01', self.product, 'LT-DEP', 'CLIENTE LOADTEST EXCEL')
        load = self._basic()
        book = load_workbook(io.BytesIO(load._export_workbook()))
        self.assertEqual(book.sheetnames[0], 'Resumen')
        for title in ('Contado', 'Según Sage sin verificar', 'Altas', 'Pendiente de localizar',
                      'Depósitos heredados', 'Cantidad contada', 'Cantidad Sage sin verificar', 'No cargado',
                      'Clientes sin casar'):
            self.assertIn(title, book.sheetnames)
        self.assertEqual([row[6].value for row in book['Altas'].iter_rows(min_row=2)], ['LT-ALTA'])
        self.assertEqual(book['Clientes sin casar'].max_row, 2)
        action = load.action_export_excel()
        self.assertEqual(action['type'], 'ir.actions.act_url')
