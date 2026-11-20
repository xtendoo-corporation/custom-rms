from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestDisassemblyV2(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.stock = cls.env['stock.warehouse'].search([('company_id', '=', cls.env.company.id)], limit=1).lot_stock_id
        cls.equipment = cls.env['product.product'].create({
            'name': 'Equipo origen', 'is_storable': True, 'tracking': 'serial', 'standard_price': 100,
        })
        cls.piece = cls.env['product.product'].create({
            'name': 'Pieza serial', 'is_storable': True, 'tracking': 'serial', 'lst_price': 10,
        })
        cls.batch = cls.env['product.product'].create({
            'name': 'Pieza lote', 'is_storable': True, 'tracking': 'lot', 'lst_price': 5,
        })
        cls.untracked = cls.env['product.product'].create({
            'name': 'Pieza sin serie', 'is_storable': True, 'tracking': 'none',
        })
        cls.lot = cls.env['stock.lot'].create({
            'name': 'EQUIPO-1', 'product_id': cls.equipment.id, 'company_id': cls.env.company.id,
        })
        cls.env['stock.quant']._update_available_quantity(cls.equipment, cls.stock, 1, lot_id=cls.lot)

    def _disassembly(self, lines):
        return self.env['rms.disassembly'].create({
            'product_id': self.equipment.id, 'lot_id': self.lot.id, 'location_id': self.stock.id,
            'cost_total': 100, 'line_ids': [Command.create(line) for line in lines],
        })

    def test_serials_and_lot_keep_origin(self):
        record = self._disassembly([
            {'product_id': self.piece.id, 'quantity': 2, 'serial': 'FAB-1,\nFAB-2'},
            {'product_id': self.batch.id, 'quantity': 3, 'serial': 'LOTE-FAB'},
        ])
        record.action_done()
        self.assertEqual(set(record.piece_lot_ids.mapped('name')), {'FAB-1', 'FAB-2', 'LOTE-FAB'})
        self.assertEqual(record.piece_lot_ids.mapped('rms_origin_disassembly_id'), record)
        self.assertEqual(record.piece_lot_ids.mapped('rms_origin_lot_id'), self.lot)
        self.assertEqual(set(record.piece_lot_ids.mapped('product_state_id.code')), {'second_hand'})
        self.assertEqual(record.allocation, 'price')
        self.assertTrue(record.name.startswith('DSP/'))

    def test_missing_or_invalid_serials_are_rejected(self):
        for quantity, serial in [(2, ''), (2, 'UNO'), (2, 'UNO,DOS,TRES'), (1.5, 'UNO,DOS'), (2, 'UNO,UNO')]:
            with self.subTest(quantity=quantity, serial=serial):
                record = self._disassembly([{'product_id': self.piece.id, 'quantity': quantity, 'serial': serial}])
                with self.assertRaises(UserError):
                    record.action_done()
                self.assertEqual(record.state, 'draft')
        for serial in ('', 'LOTE1, LOTE2'):
            record = self._disassembly([{'product_id': self.batch.id, 'quantity': 2, 'serial': serial}])
            with self.assertRaises(UserError):
                record.action_done()

    def test_untracked_piece_is_rejected(self):
        record = self._disassembly([{'product_id': self.untracked.id, 'quantity': 1}])
        with self.assertRaisesRegex(UserError, 'Las piezas sin nº de serie solo pueden ser nuevas: quita'):
            record.action_done()

    def test_customer_equipment_is_rejected(self):
        self.env['stock.quant']._update_available_quantity(self.equipment, self.stock, -1, lot_id=self.lot)
        owner = self.env['res.partner'].create({'name': 'Cliente'})
        self.env['stock.quant']._update_available_quantity(self.equipment, self.stock, 1, lot_id=self.lot, owner_id=owner)
        record = self._disassembly([{'product_id': self.piece.id, 'quantity': 1, 'serial': 'SERIE-1'}])
        with self.assertRaisesRegex(UserError, 'Solo se pueden despiezar equipos nuestros'):
            record.action_done()

    def test_only_manager_validates(self):
        user = new_test_user(self.env, login='disassembly_tech_v2',
                             groups='stock.group_stock_user,repair_security.group_repair_user')
        record = self._disassembly([{'product_id': self.piece.id, 'quantity': 1, 'serial': 'SERIE-1'}])
        with self.assertRaises(AccessError):
            record.with_user(user).action_done()
