from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError

class TestProductState(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Get states
        cls.state_new = cls.env.ref('rms_product_state.state_new')
        cls.state_demo = cls.env.ref('rms_product_state.state_demo')
        cls.state_ex_demo = cls.env.ref('rms_product_state.state_ex_demo')
        cls.state_second_hand = cls.env.ref('rms_product_state.state_second_hand')
        cls.state_discontinued = cls.env.ref('rms_product_state.state_discontinued')

        # Create partner
        cls.partner = cls.env['res.partner'].create({
            'name': 'Test Partner',
        })

        # Create product template with tracking by lot/serial number
        cls.product_tmpl = cls.env['product.template'].create({
            'name': 'Test Product State',
            'list_price': 100.0,
            'tracking': 'serial',
        })
        cls.product = cls.product_tmpl.product_variant_id

    def test_01_default_state(self):
        # Product template should have 'new' state by default
        self.assertEqual(self.product_tmpl.product_state_id, self.state_new)

        # Lot should get product state by default
        lot = self.env['stock.lot'].create({
            'name': 'SN-001',
            'product_id': self.product.id,
            'company_id': self.env.company.id,
        })
        # Simulate onchange
        lot._onchange_product_id_set_state()
        self.assertEqual(lot.product_state_id, self.state_new)

    def test_02_demo_validation(self):
        # Create sale order
        sale_order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
        })

        # A lot in Demo state can't be added as a serial (not in the allowed state list)
        lot_demo = self.env['stock.lot'].create({
            'name': 'SN-DEMO',
            'product_id': self.product.id,
            'product_state_id': self.state_demo.id,
            'company_id': self.env.company.id,
        })
        line = self.env['sale.order.line'].create({
            'order_id': sale_order.id,
            'product_id': self.product.id,
        })
        with self.assertRaises(ValidationError):
            self.env['sale.order.line.serial'].create({
                'sale_order_line_id': line.id,
                'lot_id': lot_demo.id,
            })

        # Change product template state to Demo
        self.product_tmpl.product_state_id = self.state_demo

        # Trying to add product in Demo state should also raise ValidationError
        with self.assertRaises(ValidationError):
            self.env['sale.order.line'].create({
                'order_id': sale_order.id,
                'product_id': self.product.id,
            })

    def test_03_pricing_rules(self):
        # Create ex-demo lot with custom price
        lot_ex_demo = self.env['stock.lot'].create({
            'name': 'SN-EX-DEMO',
            'product_id': self.product.id,
            'product_state_id': self.state_ex_demo.id,
            'custom_price': 80.0,
            'company_id': self.env.company.id,
        })

        # Create second-hand lot with custom price
        lot_second_hand = self.env['stock.lot'].create({
            'name': 'SN-SECOND-HAND',
            'product_id': self.product.id,
            'product_state_id': self.state_second_hand.id,
            'custom_price': 60.0,
            'company_id': self.env.company.id,
        })

        sale_order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
        })

        # Line with Ex-Demo serial
        line_ex_demo = self.env['sale.order.line'].create({
            'order_id': sale_order.id,
            'product_id': self.product.id,
            'product_uom_qty': 1,
        })
        self.env['sale.order.line.serial'].create({
            'sale_order_line_id': line_ex_demo.id,
            'lot_id': lot_ex_demo.id,
        })
        self.assertEqual(line_ex_demo.price_unit, 80.0)
        self.assertEqual(line_ex_demo.discount, 0.0)

        # Line with Second-Hand serial
        line_second_hand = self.env['sale.order.line'].create({
            'order_id': sale_order.id,
            'product_id': self.product.id,
            'product_uom_qty': 1,
        })
        self.env['sale.order.line.serial'].create({
            'sale_order_line_id': line_second_hand.id,
            'lot_id': lot_second_hand.id,
        })
        self.assertEqual(line_second_hand.price_unit, 60.0)
        self.assertEqual(line_second_hand.discount, 10.0)

    def test_05_multiple_serials_same_line(self):
        # Two second-hand lots with different custom prices grouped in one line
        lot_a = self.env['stock.lot'].create({
            'name': 'SN-SH-A',
            'product_id': self.product.id,
            'product_state_id': self.state_second_hand.id,
            'custom_price': 50.0,
            'company_id': self.env.company.id,
        })
        lot_b = self.env['stock.lot'].create({
            'name': 'SN-SH-B',
            'product_id': self.product.id,
            'product_state_id': self.state_second_hand.id,
            'custom_price': 70.0,
            'company_id': self.env.company.id,
        })

        sale_order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
        })
        line = self.env['sale.order.line'].create({
            'order_id': sale_order.id,
            'product_id': self.product.id,
            'product_uom_qty': 2,
        })
        self.env['sale.order.line.serial'].create([
            {'sale_order_line_id': line.id, 'lot_id': lot_a.id},
            {'sale_order_line_id': line.id, 'lot_id': lot_b.id},
        ])
        # Average unit price = (50 + 70) / 2 = 60
        self.assertEqual(line.price_unit, 60.0)
        self.assertEqual(line.discount, 10.0)

        # Selling the same lot again in another active order line must be blocked
        other_order = self.env['sale.order'].create({'partner_id': self.partner.id})
        other_line = self.env['sale.order.line'].create({
            'order_id': other_order.id,
            'product_id': self.product.id,
            'product_uom_qty': 1,
        })
        with self.assertRaises(ValidationError):
            self.env['sale.order.line.serial'].create({
                'sale_order_line_id': other_line.id,
                'lot_id': lot_a.id,
            })

    def test_04_cron_archive_discontinued(self):
        # Set product template to discontinued state
        self.product_tmpl.product_state_id = self.state_discontinued
        self.product_tmpl.active = True

        # Run cron function
        self.env['product.template']._cron_archive_discontinued_products()

        # Since qty_available is 0 (no stock), the product should be archived
        self.assertFalse(self.product_tmpl.active)
