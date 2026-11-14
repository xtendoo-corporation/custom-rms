# -*- coding: utf-8 -*-
from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestRmsRepairSat(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.warehouse = cls.env['stock.warehouse'].search([('company_id', '=', cls.company.id)], limit=1)
        cls.warehouse.code = 'RMS1'
        cls.summary = cls.env['stock.warehouse']._rms_setup_sat()
        cls.stock = cls.warehouse.lot_stock_id
        cls.categ = cls.env['product.category'].create({'name': 'SAT test', 'property_cost_method': 'average'})
        cls.second_hand = cls.env['product.state'].search([('code', '=', 'second_hand')], limit=1)
        cls.new_state = cls.env['product.state'].search([('code', '=', 'new')], limit=1)
        cls.customer = cls.env['res.partner'].create({'name': 'Cliente SAT'})
        cls.factory = cls.env['res.partner'].create({'name': 'Fábrica'})
        cls.desk = cls.env['product.product'].create({
            'name': 'Mesa X', 'is_storable': True, 'tracking': 'serial', 'categ_id': cls.categ.id,
            'standard_price': 1000.0, 'lst_price': 3000.0})
        cls.fader = cls.env['product.product'].create({
            'name': 'Fader', 'is_storable': True, 'tracking': 'serial', 'categ_id': cls.categ.id,
            'standard_price': 50.0, 'lst_price': 100.0})
        cls.screen = cls.env['product.product'].create({
            'name': 'Pantalla', 'is_storable': True, 'tracking': 'serial', 'categ_id': cls.categ.id,
            'standard_price': 150.0, 'lst_price': 300.0})
        cls.knob = cls.env['product.product'].create({
            'name': 'Potenciómetro', 'is_storable': True, 'tracking': 'none', 'categ_id': cls.categ.id,
            'standard_price': 1.0, 'lst_price': 2.0})

    def _stock_lot(self, product, name, state, qty=1, location=None, price=0.0):
        lot = self.env['stock.lot'].create({'product_id': product.id, 'name': name, 'company_id': self.company.id,
                                            'product_state_id': state.id, 'custom_price': price})
        self.env['stock.quant']._update_available_quantity(product, location or self.stock, qty, lot_id=lot)
        return lot

    def _repair(self, **vals):
        values = {'partner_id': self.customer.id, 'product_id': self.desk.id, 'rms_site': 'madrid',
                  'rms_serial_in': 'MESA-CLI-1', 'rms_fault': 'No enciende', 'rms_accessories': 'Fuente'}
        values.update(vals)
        return self.env['repair.order'].create(values)

    # ------------------------------------------------------------------
    def test_01_setup_sat_idempotent(self):
        self.assertTrue(self.warehouse.rms_sat_location_id)
        self.assertEqual(self.warehouse.rms_sat_location_id.name, 'SAT Madrid')
        self.assertEqual(self.warehouse.rms_sat_factory_location_id.location_id, self.warehouse.rms_sat_location_id)
        ptype = self.warehouse.rms_sat_picking_type_id
        self.assertEqual(ptype.code, 'repair_operation')
        self.assertEqual(ptype.default_product_location_src_id, self.warehouse.rms_sat_location_id)
        self.assertEqual(ptype.default_location_src_id, self.stock)
        again = self.env['stock.warehouse']._rms_setup_sat()
        self.assertFalse(again['creadas'])
        self.assertTrue(self.env['stock.location']._rms_disassembly_location(self.company, create=False))

    def test_02_entry_without_valuation_and_stages(self):
        repair = self._repair()
        self.assertEqual(repair.picking_type_id, self.warehouse.rms_sat_picking_type_id)
        self.assertEqual(repair.rms_stage, 'received')
        repair.action_rms_register_entry()
        self.assertEqual(repair.lot_id.name, 'MESA-CLI-1')
        move = repair.rms_entry_move_id
        self.assertEqual(move.state, 'done')
        self.assertEqual(move.restrict_partner_id, self.customer)
        self.assertEqual(move.move_line_ids.owner_id, self.customer)
        self.assertFalse(move.is_valued, 'El equipo del cliente no debe valorarse')
        self.assertFalse(move.value)
        quant = self.env['stock.quant'].search([('lot_id', '=', repair.lot_id.id),
                                                ('location_id', '=', self.warehouse.rms_sat_location_id.id)])
        self.assertEqual(quant.quantity, 1)
        self.assertEqual(quant.owner_id, self.customer)
        self.assertEqual(self.desk.total_value, 0)
        # Fábrica (RA)
        wizard = self.env['rms.repair.factory.wizard'].create(
            {'repair_id': repair.id, 'partner_id': self.factory.id, 'rma_number': 'RMA-77'})
        wizard.action_confirm()
        self.assertEqual(repair.rms_stage, 'factory')
        with self.assertRaises(UserError):
            repair.action_rms_deliver()
        self.assertIn(repair, self.env['repair.order'].search([('rms_stage', '=', 'factory')]))
        repair.action_rms_back_from_factory()
        self.assertEqual(repair.rms_stage, 'repair')
        self.assertTrue(repair.rms_factory_back_date)
        # Fase y días
        self.assertEqual(repair.rms_days_stage, 0)
        self.assertFalse(repair.rms_late)
        repair.rms_stage_date = '2020-01-01 00:00:00'
        repair.invalidate_recordset(['rms_late', 'rms_days_stage'])
        self.assertTrue(repair.rms_late)
        # Entrega
        repair.action_rms_deliver()
        self.assertEqual(repair.rms_stage, 'delivered')
        self.assertFalse(repair.rms_exit_move_id.is_valued)
        self.assertFalse(self.env['stock.quant'].search([
            ('lot_id', '=', repair.lot_id.id), ('location_id', 'child_of', self.warehouse.rms_sat_location_id.id),
            ('quantity', '!=', 0)]))

    def test_03_quote_used_alternative_and_repair_done(self):
        new_lot = self._stock_lot(self.fader, 'FADER-NEW', self.new_state)
        used_lot = self._stock_lot(self.fader, 'FADER-USED', self.second_hand, price=40.0)
        repair = self._repair(move_ids=[Command.create({
            'product_id': self.fader.id, 'product_uom_qty': 1, 'repair_line_type': 'add'})])
        repair.action_rms_register_entry()
        repair.action_create_sale_order()
        self.assertEqual(repair.rms_stage, 'quoted')
        order = repair.sale_order_id
        repair.action_rms_add_used_alternative()
        section = order.order_line.filtered('rms_used_section')
        self.assertTrue(section.is_optional)
        alt = order.order_line.filtered('rms_used_alternative_of_id')
        self.assertEqual(alt.rms_used_lot_id, used_lot)
        self.assertEqual(alt.price_unit, 40.0)
        self.assertEqual(alt.product_uom_qty, 0)
        original = alt.rms_used_alternative_of_id
        self.assertEqual(original.price_unit, 100.0)
        repair.action_rms_choose_used()
        self.assertEqual(repair.rms_stage, 'accepted')
        self.assertEqual(alt.product_uom_qty, 1)
        self.assertEqual(original.product_uom_qty, 0)
        # 40 € del lote de 2ª mano con el 10 % automático de rms_product_state.
        self.assertEqual(alt.price_unit, 40.0)
        self.assertAlmostEqual(order.amount_untaxed, 36.0)
        self.assertEqual(alt.serial_ids.lot_id, used_lot)
        self.assertEqual(alt.serial_state_name, self.second_hand.name)
        repair.action_validate()
        repair.action_repair_start()
        self.assertEqual(repair.rms_stage, 'repair')
        part = repair.move_ids.filtered(lambda m: m.repair_line_type == 'add')
        self.assertEqual(part.move_line_ids.lot_id, used_lot)
        repair.action_repair_end()
        self.assertEqual(repair.state, 'done')
        self.assertEqual(repair.rms_stage, 'ready')
        self.assertEqual(part.state, 'done')
        self.assertEqual(self.fader.with_context(lot_id=used_lot.id).qty_available, 0)
        self.assertEqual(self.fader.with_context(lot_id=new_lot.id).qty_available, 1)
        # El movimiento del equipo al terminar lleva propietario = cliente
        product_move = repair.move_id
        self.assertTrue(product_move)
        self.assertEqual(product_move.move_line_ids.owner_id, self.customer)
        self.assertFalse(product_move.is_valued)
        negative = self.env['stock.quant'].search([('product_id', '=', self.desk.id), ('quantity', '<', 0),
                                                   ('location_id.usage', '=', 'internal')])
        sat_quant = self.env['stock.quant'].search([('lot_id', '=', repair.lot_id.id),
                                                    ('location_id', '=', self.warehouse.rms_sat_location_id.id)])
        self.assertEqual((sat_quant.quantity, sat_quant.owner_id), (1.0, self.customer))
        self.assertFalse(negative, [(q.location_id.complete_name, q.owner_id.name, q.lot_id.name, q.quantity,
                                     repair.product_location_src_id.complete_name,
                                     repair.product_location_dest_id.complete_name) for q in negative])
        repair.action_rms_deliver()
        self.assertEqual(repair.rms_stage, 'delivered')

    def test_04_disassembly_cost_split(self):
        desk_lot = self._stock_lot(self.desk, 'MESA-VIEJA', self.second_hand)
        dis = self.env['rms.disassembly'].create({
            'product_id': self.desk.id, 'lot_id': desk_lot.id, 'location_id': self.stock.id, 'cost_total': 600.0,
            'line_ids': [Command.create({'product_id': self.fader.id, 'quantity': 2}),
                         Command.create({'product_id': self.screen.id, 'quantity': 1, 'serial': 'PANT-ORIG'}),
                         Command.create({'product_id': self.knob.id, 'quantity': 4})],
        })
        dis.action_save_bom()
        self.assertEqual(len(dis.bom_id.bom_line_ids), 3)
        dis.action_done()
        self.assertEqual(dis.state, 'done')
        self.assertTrue(dis.name.startswith('DESP/'))
        self.assertEqual(self.desk.with_context(lot_id=desk_lot.id).qty_available, 0)
        # Pesos por precio: fader 2*100, pantalla 300, potenciómetro 4*2 -> 508
        fader_line, screen_line, knob_line = dis.line_ids
        self.assertAlmostEqual(fader_line.cost_unit, 600 * 200 / 508 / 2, places=2)
        self.assertAlmostEqual(screen_line.cost_unit, 600 * 300 / 508, places=2)
        self.assertEqual(len(fader_line.lot_ids), 2)
        self.assertEqual(screen_line.lot_ids.name, 'PANT-ORIG')
        self.assertFalse(knob_line.lot_ids)
        self.assertEqual(set(dis.piece_lot_ids.mapped('product_state_id.code')), {'second_hand'})
        in_moves = dis.move_ids.filtered(lambda m: m.location_dest_id == self.stock)
        self.assertAlmostEqual(sum(in_moves.mapped('value')), 600.0, places=1)
        self.assertEqual(self.fader.with_context(location=self.stock.id).qty_available, 2)
        self.assertEqual(dis.action_print_labels()['type'], 'ir.actions.report')
        with self.assertRaises(UserError):
            dis.action_done()
        # El lote despiezado ya no está: otro despiece del mismo equipo falla.
        again = dis.copy({'lot_id': desk_lot.id})
        with self.assertRaises(UserError):
            again.action_done()
        # Botón desde la ficha del lote
        action = desk_lot.action_rms_disassemble()
        self.assertEqual(action['context']['default_lot_id'], desk_lot.id)

    def test_05_permissions(self):
        # El hook deja con permiso de reparaciones a quien tenía Inventario (admin incluido).
        manager = self.env.ref('repair_security.group_repair_manager')
        self.assertIn(self.env.ref('base.user_admin'), manager.all_user_ids)
        user = new_test_user(self.env, login='sat_tech', groups='stock.group_stock_user,repair_security.group_repair_user')
        dis = self.env['rms.disassembly'].with_user(user).create({
            'product_id': self.desk.id, 'location_id': self.stock.id})
        with self.assertRaises(AccessError):
            dis.unlink()
        with self.assertRaises(AccessError):
            self.env['rms.repair.sat.sage.import'].with_user(user).create({})
        self.assertTrue(self.env.ref('rms_repair_sat.menu_rms_sat_root').with_user(user)._filter_visible_menus())

    def test_07_kanban_groups(self):
        """El kanban agrupa por fase sin errores (todas las fases como columnas)."""
        self._repair()
        groups = self.env['repair.order'].with_context(read_group_expand=True).web_read_group(
            [], ['rms_stage'], aggregates=['__count'])['groups']
        self.assertEqual(len(groups), 9)

    def test_06_sage_import(self):
        if 'rms.sage.stock.line' not in self.env:
            wizard = self.env['rms.repair.sat.sage.import'].create({})
            self.assertFalse(wizard.available)
            with self.assertRaises(UserError):
                wizard.action_import()
            return
        brand = self.env['product.category'].create({'name': 'Marca SAT test'})
        snapshot = self.env['rms.sage.snapshot'].create({'name': 'SAT test', 'sage_company_code': '01',
                                                          'company_id': self.company.id,
                                                          'brand_categ_id': brand.id})
        Line = self.env['rms.sage.stock.line']
        base = {'snapshot_id': snapshot.id, 'is_current': True, 'article_code': 'MX', 'model_code': 'MX',
                'quantity': 1, 'match_state': 'ok'}
        Line.create([dict(base, warehouse_code='AL8', serial='SAGE-1', product_id=self.desk.id),
                     dict(base, warehouse_code='STS', serial='SAGE-2', product_id=self.desk.id),
                     dict(base, warehouse_code='STM', serial='SAGE-3'),
                     dict(base, warehouse_code='AL1', serial='SAGE-4', product_id=self.desk.id)])
        wizard = self.env['rms.repair.sat.sage.import'].create({})
        self.assertEqual(wizard.preview_count, 3)
        self.assertEqual(wizard.unmatched_count, 1)
        action = wizard.action_import()
        repairs = self.env['repair.order'].browse(action['domain'][0][2])
        self.assertEqual(len(repairs), 2)
        self.assertEqual(set(repairs.mapped('rms_site')), {'madrid', 'sevilla'})
        self.assertEqual(repairs.partner_id.name, 'Cliente pendiente de asignar (SAT)')
        again = self.env['rms.repair.sat.sage.import'].create({}).action_import()
        self.assertFalse(again['domain'][0][2])
