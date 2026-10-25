from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged('post_install', '-at_install')
class TestServerRestrictions(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not cls.env.ref('custom.comerciales', raise_if_not_found=False):
            group = cls.env['res.groups'].create({'name': 'Comerciales prueba F1'})
            cls.env['ir.model.data'].create({
                'module': 'custom', 'name': 'comerciales',
                'model': 'res.groups', 'res_id': group.id,
            })
        cls.user = new_test_user(cls.env, login='f1_rms_product_state', groups='base.group_user,sales_team.group_sale_salesman,custom.comerciales')
        cls.partner = cls.env['res.partner'].create({'name': 'Cliente F1'})
        cls.product = cls.env['product.product'].create({
            'name': 'Producto F1', 'list_price': 100,
            'is_storable': True, 'tracking': 'serial',
        })
        cls.order = cls.env['sale.order'].create({'partner_id': cls.partner.id, 'user_id': cls.user.id})
        cls.line = cls.env['sale.order.line'].create({'order_id': cls.order.id, 'product_id': cls.product.id})

    def test_state_read_only(self):
        internal = new_test_user(self.env, login='f1_internal_state', groups='base.group_user')
        state = self.env.ref('rms_product_state.state_second_hand').with_user(internal)
        self.assertTrue(state.name)
        with self.assertRaises(AccessError), self.cr.savepoint():
            state.write({'name': 'Alterado'})
        with self.assertRaises(AccessError), self.cr.savepoint():
            state.create({'name': 'Alterado', 'code': 'f1'})
        with self.assertRaises(AccessError), self.cr.savepoint():
            state.unlink()

    def test_serial_product_and_price(self):
        lot = self.env['stock.lot'].create({
            'name': 'F1-SERIAL', 'product_id': self.product.id,
            'company_id': self.env.company.id,
            'product_state_id': self.env.ref('rms_product_state.state_second_hand').id,
            'custom_price': 60,
        })
        serial = self.env['sale.order.line.serial'].with_user(self.user).create({
            'lot_id': lot.id, 'sale_order_line_id': self.line.id, 'price_unit': 1,
        })
        self.assertEqual(serial.price_unit, 60)
        self.assertEqual(self.line.price_unit, 60)
        self.assertEqual(self.line.discount, 10)
        serial.write({'price_unit': 2})
        self.assertEqual(serial.price_unit, 60)
        other = self.env['product.product'].create({
            'name': 'Otro F1', 'list_price': 100,
            'is_storable': True, 'tracking': 'serial',
        })
        wrong = self.env['stock.lot'].create({
            'name': 'F1-WRONG', 'product_id': other.id,
            'company_id': self.env.company.id,
            'product_state_id': lot.product_state_id.id,
        })
        with self.assertRaises(ValidationError), self.cr.savepoint():
            serial.write({'lot_id': wrong.id})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['sale.order.line.serial'].create({'lot_id': wrong.id, 'sale_order_line_id': self.line.id})
