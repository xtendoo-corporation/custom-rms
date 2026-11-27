import base64

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestFactoryV4(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env['stock.warehouse'].search([('company_id', '=', cls.env.company.id)], limit=1)
        cls.warehouse.code = 'RMS1'
        cls.env['stock.warehouse']._rms_setup_sat()
        cls.customer = cls.env['res.partner'].create({'name': 'Cliente fábrica v4'})
        cls.contact = cls.env['res.partner'].create({'name': 'Contacto', 'parent_id': cls.customer.id})
        cls.vendor = cls.env['res.partner'].create({'name': 'Fábrica v4'})
        cls.product = cls.env['product.product'].create({'name': 'Equipo v4', 'is_storable': True,
                                                          'tracking': 'serial', 'standard_price': 100})
        cls.accessory = cls.env.ref('rms_repair_sat.accessory_none')

    def _entry(self, serial, owner='customer'):
        repair = self.env['repair.order'].create({
            'partner_id': self.customer.id, 'rms_contact_id': self.contact.id,
            'product_id': self.product.id, 'rms_site': 'madrid', 'rms_serial_in': serial,
            'rms_fault': 'No funciona', 'rms_owner_type': owner,
            'rms_accessory_ids': [Command.set(self.accessory.ids)],
        })
        self.env['ir.attachment'].create({'name': 'foto.png', 'res_model': 'repair.order',
            'res_id': repair.id, 'mimetype': 'image/png', 'datas': base64.b64encode(b'foto')})
        repair.action_rms_register_entry()
        repair.under_warranty = True
        return repair

    def _send(self, repair):
        self.env['rms.repair.factory.wizard'].create({
            'repair_id': repair.id, 'partner_id': self.vendor.id, 'rma_number': 'RMA-V4'}).action_confirm()

    def _quantity(self, repair, location, owner=False):
        return sum(self.env['stock.quant'].search([('product_id', '=', repair.product_id.id),
            ('lot_id', '=', repair.lot_id.id), ('location_id', '=', location.id),
            ('owner_id', '=', owner.id if owner else False)]).mapped('quantity'))

    def test_warranty_rejected_on_factory_return(self):
        repair = self._entry('V4-RETURN')
        self._send(repair)
        self.env['rms.repair.factory.return.wizard'].create({'repair_id': repair.id,
            'result': 'warranty_rejected', 'warranty_rejected_reason': 'Daño externo'}).action_confirm()
        self.assertEqual(repair.rms_factory_result, 'warranty_rejected')
        self.assertEqual(repair.rms_stage, 'diagnosis')
        self.assertFalse(repair.under_warranty)
        self.assertTrue(repair.rms_warranty_rejected)
        self.assertEqual(repair.rms_warranty_rejected_date, fields.Date.context_today(repair))
        self.assertEqual(repair.rms_warranty_rejected_reason, 'Daño externo')
        self.assertEqual(self._quantity(repair, self.warehouse.rms_sat_location_id, self.customer), 1)
        self.assertEqual(self._quantity(repair, self.warehouse.rms_sat_factory_location_id, self.customer), 0)
        activities = self.env['mail.activity'].search([('res_model', '=', 'repair.order'), ('res_id', '=', repair.id)])
        self.assertIn('Hacer presupuesto: la fábrica ha rechazado la garantía', activities.mapped('summary'))

    def test_warranty_rejected_without_return_after_swap(self):
        repair = self._entry('V4-SWAP-BAD')
        replacement = self.env['stock.lot'].create({'name': 'V4-SWAP-NEW', 'product_id': self.product.id,
                                                     'company_id': self.env.company.id})
        self.env['stock.quant']._update_available_quantity(self.product, self.warehouse.lot_stock_id, 1, lot_id=replacement)
        self.env['rms.repair.swap.wizard'].create({'repair_id': repair.id, 'product_id': self.product.id,
                                                   'lot_id': replacement.id}).action_confirm()
        self.env['rms.repair.warranty.reject.wizard'].create({'repair_id': repair.id,
            'reason': 'No cubre daños'}).action_confirm()
        self.assertFalse(repair.under_warranty)
        self.assertEqual(repair.rms_stage, 'diagnosis')
        self.assertEqual(self._quantity(repair, self.warehouse.rms_ra_location_id), 1)
        activities = self.env['mail.activity'].search([('res_model', '=', 'repair.order'), ('res_id', '=', repair.id)])
        self.assertTrue(any('decidir si se factura' in a.summary and replacement.name in a.summary for a in activities))
        self.assertFalse(repair.sale_order_id)

    def test_destroy_from_ra_and_customer_is_forbidden(self):
        customer_repair = self._entry('V4-CUSTOMER')
        with self.assertRaisesRegex(UserError, 'Solo se destruyen unidades nuestras'):
            customer_repair.action_rms_destroy_factory()
        own = self._entry('V4-OWN', owner='company')
        own._rms_customer_move(self.warehouse.rms_sat_location_id, self.warehouse.rms_ra_location_id, 'A RA')
        self.env['rms.repair.destroy.wizard'].create({'repair_id': own.id,
            'authorization_ref': 'AUTH-42', 'note': 'Autorizado'}).action_confirm()
        self.assertEqual(own.rms_factory_result, 'destroyed')
        self.assertEqual(own.rms_stage, 'delivered')
        self.assertEqual(own.rms_destroyed_authorization_ref, 'AUTH-42')
        self.assertEqual(self._quantity(own, self.warehouse.rms_ra_location_id), 0)
        self.assertEqual(self._quantity(own, own.rms_destroyed_move_id.location_dest_id), 1)
        self.assertEqual(own.rms_destroyed_move_id.location_dest_id.usage, 'inventory')

    def test_destroy_at_factory_through_return_wizard(self):
        repair = self._entry('V4-FACTORY', owner='company')
        self._send(repair)
        self.env['rms.repair.factory.return.wizard'].create({'repair_id': repair.id, 'result': 'destroyed',
            'authorization_ref': 'FAB-42'}).action_confirm()
        self.assertEqual(repair.rms_stage, 'delivered')
        self.assertEqual(repair.rms_factory_result, 'destroyed')
        self.assertTrue(repair.rms_factory_back_date)
        self.assertEqual(self._quantity(repair, self.warehouse.rms_sat_factory_location_id), 0)
        self.assertEqual(self._quantity(repair, repair.rms_destroyed_move_id.location_dest_id), 1)

    def test_rejection_while_unit_still_at_factory_then_return(self):
        repair = self._entry('V4-STAYS-FACTORY')
        self._send(repair)
        self.env['rms.repair.warranty.reject.wizard'].create({'repair_id': repair.id,
            'reason': 'No cubierto'}).action_confirm()
        self.assertEqual(repair.rms_stage, 'diagnosis')
        self.assertTrue(repair.rms_physically_at_factory)
        with self.assertRaisesRegex(UserError, 'sigue en fábrica'):
            repair.action_rms_deliver()
        with self.assertRaisesRegex(UserError, 'sigue en fábrica'):
            repair.action_rms_send_factory()
        self.env['rms.repair.factory.return.wizard'].create({'repair_id': repair.id,
            'result': 'repaired'}).action_confirm()
        repair.invalidate_recordset(['rms_physically_at_factory'])
        self.assertFalse(repair.rms_physically_at_factory)
        self.assertEqual(repair.rms_stage, 'diagnosis')
        self.assertEqual(self._quantity(repair, self.warehouse.rms_sat_location_id, self.customer), 1)
