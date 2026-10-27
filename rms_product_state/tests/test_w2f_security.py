from unittest.mock import patch

from psycopg2 import IntegrityError

from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged('post_install', '-at_install')
class TestW2FSecurity(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.internal = new_test_user(cls.env, login='w2f_internal', groups='base.group_user')
        cls.salesman = new_test_user(cls.env, login='w2f_salesman', groups='sales_team.group_sale_salesman')
        cls.manager = new_test_user(cls.env, login='w2f_manager', groups='sales_team.group_sale_manager')
        cls.stock = new_test_user(cls.env, login='w2f_stock', groups='stock.group_stock_user')
        cls.product = cls.env['product.product'].create({'name': 'Producto W2F', 'tracking': 'serial'})
        cls.order = cls.env['sale.order'].create({
            'partner_id': cls.internal.partner_id.id, 'user_id': cls.salesman.id,
        })
        cls.line = cls.env['sale.order.line'].create({
            'order_id': cls.order.id, 'product_id': cls.product.id,
        })
        cls.lot = cls.env['stock.lot'].create({
            'name': 'W2F-SERIAL', 'product_id': cls.product.id,
            'company_id': cls.env.company.id,
            'product_state_id': cls.env.ref('rms_product_state.state_second_hand').id,
        })
        cls.serial = cls.env['sale.order.line.serial'].create({
            'sale_order_line_id': cls.line.id, 'lot_id': cls.lot.id,
        })

    def test_serial_access(self):
        with self.assertRaises(AccessError):
            self.serial.with_user(self.internal).read(['lot_id'])
        self.assertTrue(self.serial.with_user(self.salesman).read(['lot_id']))
        self.assertTrue(self.serial.with_user(self.stock).read(['lot_id']))
        with self.assertRaises(AccessError):
            self.serial.with_user(self.stock).write({'price_unit': 1})
        self.order.user_id = self.manager
        with self.assertRaises(AccessError):
            self.serial.with_user(self.salesman).read(['lot_id'])
        self.assertTrue(self.serial.with_user(self.manager).read(['lot_id']))
        self.order.user_id = False
        self.assertTrue(self.serial.with_user(self.salesman).read(['lot_id']))

    def test_serial_company_rule(self):
        other_company = self.env['res.company'].create({'name': 'Compañía W2F'})
        other_partner = self.env['res.partner'].create({'name': 'Cliente W2F'})
        order = self.env['sale.order'].with_company(other_company).create({
            'partner_id': other_partner.id, 'user_id': self.manager.id,
        })
        line = self.env['sale.order.line'].create({'order_id': order.id, 'product_id': self.product.id})
        lot = self.lot.copy({'name': 'W2F-OTHER', 'company_id': other_company.id})
        serial = self.env['sale.order.line.serial'].create({'sale_order_line_id': line.id, 'lot_id': lot.id})
        with self.assertRaises(AccessError):
            serial.with_user(self.manager).with_context(allowed_company_ids=[self.env.company.id]).read(['lot_id'])

    def test_state_read_only(self):
        state = self.env.ref('rms_product_state.state_second_hand').with_user(self.internal)
        self.assertTrue(state.read(['name']))
        with self.assertRaises(AccessError):
            state.write({'name': 'Cambio W2F'})
        with self.assertRaises(AccessError):
            state.create({'name': 'Estado W2F', 'code': 'w2f'})
        with self.assertRaises(AccessError):
            state.unlink()

    def test_unique_constraints(self):
        with self.assertRaises(IntegrityError), self.cr.savepoint():
            self.env.ref('rms_product_state.state_second_hand').copy()
            self.env.flush_all()
        with self.assertRaises(IntegrityError), self.cr.savepoint():
            self.serial.copy()
            self.env.flush_all()

    def test_cron_continues_after_message_failure(self):
        state = self.env.ref('rms_product_state.state_discontinued')
        products = self.env['product.template'].create([
            {'name': 'W2F fallo', 'product_state_id': state.id},
            {'name': 'W2F siguiente', 'product_state_id': state.id},
        ])
        original = type(products).message_post

        def message_post(product, **kwargs):
            if product.id == products[0].id:
                raise ValueError('Fallo de mensaje de prueba')
            return original(product, **kwargs)

        with patch.object(type(products), 'message_post', message_post):
            products._cron_archive_discontinued_products()
        self.assertTrue(products[0].active)
        self.assertFalse(products[1].active)
