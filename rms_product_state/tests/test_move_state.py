from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMoveProductState(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.demo = cls.env.ref('rms_product_state.state_demo')
        cls.new = cls.env.ref('rms_product_state.state_new')
        cls.second_hand = cls.env.ref('rms_product_state.state_second_hand')
        cls.warehouse = cls.env['stock.warehouse'].search([
            ('company_id', '=', cls.env.company.id),
        ], limit=1)
        cls.stock = cls.warehouse.lot_stock_id
        cls.destination = cls.env['stock.location'].create({
            'name': 'State preservation destination',
            'location_id': cls.stock.id,
            'company_id': cls.env.company.id,
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Serial state preservation', 'is_storable': True,
            'tracking': 'serial',
        })
        cls.lot = cls.env['stock.lot'].create({
            'name': 'PRESERVE-DEMO', 'product_id': cls.product.id,
            'company_id': cls.env.company.id, 'product_state_id': cls.demo.id,
        })
        cls.env['stock.quant']._update_available_quantity(
            cls.product, cls.stock, 1, lot_id=cls.lot,
        )

    def _move(self, source, destination, **line_values):
        move = self.env['stock.move'].create({
            'product_id': self.product.id,
            'product_uom_qty': 1, 'product_uom': self.product.uom_id.id,
            'location_id': source.id, 'location_dest_id': destination.id,
            'company_id': self.env.company.id,
        })
        move._action_confirm()
        values = {
            'move_id': move.id, 'product_id': self.product.id,
            'product_uom_id': self.product.uom_id.id, 'quantity': 1,
            'location_id': source.id, 'location_dest_id': destination.id,
            'company_id': self.env.company.id,
        }
        values.update(line_values)
        line = self.env['stock.move.line'].create(values)
        move.picked = True
        move._action_done()
        return line

    def test_inventory_keeps_demo(self):
        quant = self.env['stock.quant'].search([
            ('lot_id', '=', self.lot.id), ('location_id', '=', self.stock.id),
        ])
        quant.with_context(inventory_mode=True).inventory_quantity = 0
        quant.action_apply_inventory()
        self.assertEqual(quant.quantity, 0)
        self.assertEqual(self.lot.product_state_id, self.demo)

    def test_internal_move_keeps_demo(self):
        line = self._move(self.stock, self.destination, lot_id=self.lot.id)
        self.assertEqual(line.product_state_id, self.demo)
        self.assertEqual(self.lot.product_state_id, self.demo)

    def test_line_without_state_does_not_touch_lot(self):
        self._move(self.stock, self.destination, lot_id=self.lot.id,
                   product_state_id=False)
        self.assertEqual(self.lot.product_state_id, self.demo)

    def _receive(self, name, **values):
        # An incoming picking type authorises creating a lot from lot_name.
        supplier = self.env.ref('stock.stock_location_suppliers')
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.warehouse.in_type_id.id,
            'location_id': supplier.id, 'location_dest_id': self.stock.id,
        })
        move = self.env['stock.move'].create({
            'picking_id': picking.id,
            'product_id': self.product.id, 'product_uom_qty': 1,
            'product_uom': self.product.uom_id.id,
            'location_id': supplier.id, 'location_dest_id': self.stock.id,
        })
        picking.action_confirm()
        # Odoo crea la línea de la recepción al confirmar: se rellena esa.
        line_values = {'quantity': 1, 'lot_name': name}
        line_values.update(values)
        line = move.move_line_ids[:1]
        if line:
            line.write(line_values)
        else:
            line = self.env['stock.move.line'].create(dict(
                line_values, move_id=move.id, picking_id=picking.id,
                product_id=self.product.id, product_uom_id=self.product.uom_id.id,
                location_id=supplier.id, location_dest_id=self.stock.id))
        move.picked = True
        picking.button_validate()
        self.assertEqual(picking.state, 'done')
        self.assertTrue(line.lot_id)
        return line.lot_id

    def test_reception_explicit_second_hand(self):
        lot = self._receive('RECEIVE-SECOND', product_state_id=self.second_hand.id)
        self.assertEqual(lot.product_state_id, self.second_hand)

    def test_reception_default_new(self):
        lot = self._receive('RECEIVE-NEW')
        self.assertEqual(lot.product_state_id, self.new)

    def test_repair_keeps_demo(self):
        installed = self.env['ir.module.module'].search_count([
            ('name', '=', 'repair'), ('state', '=', 'installed'),
        ])
        if not installed:
            self.skipTest('repair is not installed (optional module)')
        repair = self.env['repair.order'].create({
            'product_id': self.product.id, 'product_qty': 1,
            'product_uom': self.product.uom_id.id, 'lot_id': self.lot.id,
            'location_id': self.stock.id,
            'location_dest_id': self.stock.id,
            'company_id': self.env.company.id,
        })
        repair.action_validate()
        repair.action_repair_start()
        repair.action_repair_end()
        self.assertEqual(repair.state, 'done')
        self.assertEqual(self.lot.product_state_id, self.demo)
