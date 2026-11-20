import base64

from odoo import Command, fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSatPackage2(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.warehouse = cls.env['stock.warehouse'].search([('company_id', '=', cls.company.id)], limit=1)
        cls.warehouse.code = 'RMS1'
        cls.env['stock.warehouse']._rms_setup_sat()
        cls.customer = cls.env['res.partner'].create({'name': 'Cliente paquete 2'})
        cls.contact = cls.env['res.partner'].create({'name': 'Contacto paquete 2', 'parent_id': cls.customer.id})
        cls.factory = cls.env['res.partner'].create({'name': 'Fábrica paquete 2'})
        cls.accessory = cls.env.ref('rms_repair_sat.accessory_none')
        cls.product = cls.env['product.product'].create({
            'name': 'Equipo paquete 2', 'type': 'consu', 'is_storable': True, 'tracking': 'serial',
            'standard_price': 100, 'lst_price': 250,
        })
        cls.part = cls.env['product.product'].create({
            'name': 'Pieza con serie', 'type': 'consu', 'is_storable': True, 'tracking': 'serial',
            'standard_price': 10, 'lst_price': 20,
        })
        cls.untracked = cls.env['product.product'].create({
            'name': 'Pieza sin serie', 'type': 'consu', 'is_storable': True, 'tracking': 'none',
            'standard_price': 5, 'lst_price': 10,
        })

    def _repair(self, serial='AVERIA-1', owner='customer'):
        repair = self.env['repair.order'].create({
            'partner_id': self.customer.id, 'rms_contact_id': self.contact.id, 'product_id': self.product.id,
            'rms_site': 'madrid', 'rms_serial_in': serial, 'rms_fault': 'No funciona',
            'rms_owner_type': owner, 'rms_entry_way': 'hand',
            'rms_accessory_ids': [Command.set(self.accessory.ids)],
        })
        self.env['ir.attachment'].create({'name': 'foto.png', 'res_model': 'repair.order', 'res_id': repair.id,
                                           'mimetype': 'image/png', 'datas': base64.b64encode(b'foto')})
        repair.action_rms_register_entry()
        return repair

    def _lot(self, name, product=None, location=None, owner=None):
        product = product or self.product
        lot = self.env['stock.lot'].create({'name': name, 'product_id': product.id, 'company_id': self.company.id})
        if location:
            self.env['stock.quant']._update_available_quantity(product, location, 1, lot_id=lot, owner_id=owner)
        return lot

    def _quantity(self, lot, location, owner=None):
        quants = self.env['stock.quant'].search([('lot_id', '=', lot.id), ('location_id', '=', location.id),
                                                  ('owner_id', '=', owner.id if owner else False)])
        return sum(quants.mapped('quantity'))

    def _send(self, repair):
        wizard = self.env['rms.repair.factory.wizard'].create({
            'repair_id': repair.id, 'partner_id': self.factory.id, 'rma_number': 'RMA-1',
            'tracking_ref': 'ENV-1', 'shipping_cost': 25, 'note': 'Nota de fábrica',
        })
        wizard.action_confirm()
        self.assertEqual(repair.rms_factory_tracking_ref, 'ENV-1')
        self.assertEqual(repair.rms_factory_shipping_cost, 25)
        self.assertEqual(repair.rms_stage, 'factory')

    def _return(self, repair, result, **values):
        return self.env['rms.repair.factory.return.wizard'].create(
            dict(repair_id=repair.id, result=result, **values)).action_confirm()

    def test_warranty_swap_ownership_and_delivery(self):
        repair = self._repair()
        old_lot = repair.lot_id
        replacement = self._lot('NUEVO-1', location=self.warehouse.lot_stock_id)
        repair.under_warranty = True
        wizard = self.env['rms.repair.swap.wizard'].create({
            'repair_id': repair.id, 'product_id': self.product.id, 'lot_id': replacement.id, 'note': 'Cambio',
        })
        wizard.action_confirm()
        customers = self.env.ref('stock.stock_location_customers')
        self.assertEqual(repair.rms_swap_picking_id.state, 'done')
        self.assertEqual(repair.rms_swap_picking_id.picking_type_id, self.warehouse.out_type_id)
        self.assertEqual(repair.rms_swap_picking_id.partner_id, self.customer)
        self.assertEqual(repair.rms_swap_lot_id, replacement)
        self.assertTrue(repair.rms_swap_done)
        self.assertEqual(repair.rms_owner_type, 'company')
        self.assertEqual(repair.rms_original_partner_id, self.customer)
        self.assertEqual(self._quantity(old_lot, self.warehouse.rms_ra_location_id), 1)
        incoming = self.env['stock.move'].search([('origin', '=', '%s · Equipo averiado en RA' % repair.name),
                                                  ('location_dest_id', '=', self.warehouse.rms_ra_location_id.id)])
        self.assertEqual(len(incoming), 1)
        self.assertTrue(incoming.is_valued)
        self.assertFalse(incoming.move_line_ids.owner_id)
        ra_move = self.env['stock.move'].search([('origin', 'like', repair.name),
            ('location_dest_id', '=', self.warehouse.rms_ra_location_id.id), ('product_id', '=', self.product.id)], limit=1)
        self.assertTrue(ra_move.is_valued)
        self.assertAlmostEqual(ra_move.value, 100, places=2)
        self.assertEqual(self._quantity(old_lot, self.warehouse.rms_sat_location_id, self.customer), 0)
        self.assertEqual(self._quantity(replacement, customers), 1)
        self.assertFalse(repair.sale_order_id)

    def test_factory_repaired_and_replaced_customer_owned(self):
        repair = self._repair()
        old_lot = repair.lot_id
        self._send(repair)
        self._return(repair, 'repaired')
        self.assertEqual(repair.rms_factory_result, 'repaired')
        self.assertEqual(self._quantity(old_lot, self.warehouse.rms_sat_location_id, self.customer), 1)
        self._send(repair)
        self._return(repair, 'replaced', new_serial='FABRICA-2')
        self.assertEqual(repair.rms_factory_result, 'replaced')
        self.assertEqual(repair.rms_original_lot_id, old_lot)
        self.assertEqual(repair.lot_id.rms_replaces_lot_id, old_lot)
        self.assertEqual(repair.lot_id.name, 'FABRICA-2')
        self.assertEqual(self._quantity(old_lot, self.warehouse.rms_sat_factory_location_id, self.customer), 0)
        self.assertEqual(self._quantity(repair.lot_id, self.warehouse.rms_sat_location_id, self.customer), 1)
        self.assertTrue(repair.rms_factory_back_date)

    def test_factory_credit_only_for_our_equipment(self):
        repair = self._repair()
        self._send(repair)
        with self.assertRaises(UserError):
            self._return(repair, 'credited', credit_ref='AB-1')
        self.assertEqual(self._quantity(repair.lot_id, self.warehouse.rms_sat_factory_location_id, self.customer), 1)
        own = self._repair(serial='AVERIA-2', owner='company')
        self._send(own)
        self._return(own, 'credited', credit_ref='AB-2')
        self.assertEqual(own.rms_factory_result, 'credited')
        self.assertEqual(own.rms_factory_credit_ref, 'AB-2')
        self.assertEqual(own.rms_stage, 'delivered')
        self.assertEqual(self._quantity(own.lot_id, self.warehouse.rms_sat_factory_location_id), 0)
        self.assertTrue(own.rms_factory_back_date)

    def test_factory_replacement_of_own_equipment(self):
        repair = self._repair(owner='company')
        previous = repair.lot_id
        self._send(repair)
        self._return(repair, 'replaced', new_serial='NUEVO-FAB')
        self.assertEqual(repair.lot_id.rms_replaces_lot_id, previous)
        self.assertEqual(self._quantity(previous, self.warehouse.rms_sat_factory_location_id), 0)
        self.assertEqual(self._quantity(repair.lot_id, self.warehouse.rms_sat_location_id), 1)

    def test_standard_operation_type_stays_archived_after_warehouse_write(self):
        warehouse = self.warehouse
        sat = warehouse.rms_sat_picking_type_id
        self.assertTrue(sat.active)
        standard = self.env['stock.picking.type'].with_context(active_test=False).search([
            ('warehouse_id', '=', warehouse.id), ('code', '=', 'repair_operation'), ('id', '!=', sat.id)])
        self.assertTrue(standard)
        self.assertFalse(standard.filtered('active'))
        self.assertEqual(warehouse.repair_type_id, sat)
        next_step = 'pick_ship' if warehouse.delivery_steps == 'ship_only' else 'ship_only'
        warehouse.write({'delivery_steps': next_step})
        self.assertTrue(sat.active)
        self.assertFalse(standard.filtered('active'))
        self.assertEqual(warehouse.repair_type_id, sat)
        self.assertEqual(self._repair().picking_type_id, sat)

    def _quote(self, repair):
        order = self.env['sale.order'].create({
            'partner_id': self.customer.id, 'warehouse_id': self.warehouse.id,
            'order_line': [Command.create({'product_id': self.part.id, 'product_uom_qty': 1,
                                           'price_unit': 20})],
        })
        repair.sale_order_id = order
        return order

    def test_waiting_part_buttons(self):
        repair = self._repair()
        repair.action_rms_wait_part()
        self.assertEqual(repair.rms_stage, 'waiting_part')
        repair.action_rms_part_received()
        self.assertEqual(repair.rms_stage, 'repair')

    def test_labour_hourly_and_fixed_update_one_line(self):
        repair = self._repair()
        order = self._quote(repair)
        repair.write({'rms_labour_mode': 'hourly', 'rms_labour_hours': 2})
        repair.action_rms_add_labour()
        hourly = order.order_line.filtered(lambda line: line.product_id.name == 'Hora de taller')
        self.assertEqual(len(hourly), 1)
        self.assertEqual(hourly.product_uom_qty, 2)
        repair.rms_labour_hours = 3
        repair.action_rms_add_labour()
        self.assertEqual(len(order.order_line.filtered(lambda line: line.product_id == hourly.product_id)), 1)
        self.assertEqual(hourly.product_uom_qty, 3)
        service = self.env['product.product'].create({'name': 'Servicio fijo SAT', 'type': 'service'})
        fixed = self.env['rms.repair.fixed.price'].create({'name': 'Trabajo fijo', 'product_id': service.id, 'price': 75})
        hourly_product = hourly.product_id
        hourly_id = hourly.id
        repair.write({'rms_labour_mode': 'fixed', 'rms_fixed_price_id': fixed.id})
        repair.action_rms_add_labour()
        self.assertFalse(order.order_line.filtered(lambda line: line.product_id == hourly_product))
        fixed_line = order.order_line.filtered(lambda line: line.product_id == service)
        self.assertEqual(len(fixed_line), 1)
        self.assertEqual(fixed_line.id, hourly_id)
        self.assertEqual(fixed_line.product_uom_qty, 1)
        self.assertEqual(fixed_line.price_unit, 75)

    def test_rejection_and_send_quote(self):
        repair = self._repair()
        order = self._quote(repair)
        action = repair.action_rms_send_quote()
        self.assertEqual(action['res_model'], 'mail.compose.message')
        self.assertEqual(repair.rms_stage, 'quoted')
        repair.action_rms_reject_quote()
        self.assertEqual(order.state, 'cancel')
        self.assertEqual(repair.rms_stage, 'uncollected')
        self.assertEqual(repair.rms_rejected_date, fields.Date.context_today(repair))

    def test_accepted_amount_requires_reapproval(self):
        repair = self._repair()
        order = self._quote(repair)
        order.action_confirm()
        self.assertEqual(repair.rms_accepted_amount, order.amount_total)
        repair.rms_max_amount = 10
        order.order_line[0].price_unit += 11
        self.assertTrue(repair.rms_needs_reapproval)
        with self.assertRaises(UserError):
            repair.action_repair_done()
        repair.action_rms_reapprove()
        self.assertTrue(repair.rms_reapproved)
        self.assertEqual(repair.rms_accepted_amount, order.amount_total)
        self.assertFalse(repair.rms_needs_reapproval)

    def test_used_alternative_excludes_untracked_product(self):
        repair = self._repair()
        repair.move_ids = [
            Command.create({'product_id': self.part.id, 'product_uom_qty': 1, 'repair_line_type': 'add'}),
            Command.create({'product_id': self.untracked.id, 'product_uom_qty': 1, 'repair_line_type': 'add'}),
        ]
        repair.action_create_sale_order()
        repair.action_rms_add_used_alternative()
        order = repair.sale_order_id
        alternatives = order.order_line.filtered('rms_used_alternative_of_id')
        self.assertEqual(alternatives.mapped('product_id'), self.part)
        section = order.order_line.filtered('rms_used_section')
        self.assertIn(self.untracked.name, section.name)
        bad_lot = self._lot('LOTE-PARA-SIN-SERIE', product=self.part)
        with self.assertRaises(ValidationError):
            self.env['sale.order.line'].create({'order_id': order.id, 'product_id': self.untracked.id,
                                                'product_uom_qty': 1, 'rms_used_lot_id': bad_lot.id})

    def test_factory_bill_repercussion(self):
        repair = self._repair()
        order = self._quote(repair)
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice', 'partner_id': self.factory.id,
            'invoice_line_ids': [Command.create({'name': 'Trabajo de fábrica', 'quantity': 1, 'price_unit': 125})],
        })
        repair.write({'rms_factory_bill_ids': [Command.set(bill.ids)], 'rms_rma_number': 'RMA-77',
                      'under_warranty': True})
        with self.assertRaises(UserError):
            repair.action_rms_add_factory_bill()
        repair.under_warranty = False
        repair.action_rms_add_factory_bill()
        product = self.env.ref('rms_repair_sat.product_factory_repair')
        lines = order.order_line.filtered(lambda line: line.product_id == product)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines.price_unit, bill.amount_untaxed)
        self.assertIn('RMA-77', lines.name)
        repair.action_rms_add_factory_bill()
        self.assertEqual(len(order.order_line.filtered(lambda line: line.product_id == product)), 1)
