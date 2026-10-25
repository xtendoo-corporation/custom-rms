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
        cls.user = new_test_user(cls.env, login='f1_rms_ventas_restriccion_comerciales', groups='base.group_user,sales_team.group_sale_salesman,custom.comerciales')
        cls.partner = cls.env['res.partner'].create({'name': 'Cliente F1'})
        cls.product = cls.env['product.product'].create({'name': 'Producto F1', 'list_price': 100})
        cls.order = cls.env['sale.order'].create({'partner_id': cls.partner.id, 'user_id': cls.user.id})
        cls.line = cls.env['sale.order.line'].create({'order_id': cls.order.id, 'product_id': cls.product.id})

    def test_write_ignores_protected_fields(self):
        fields = [f for f in ('price_unit', 'discount', 'discount1', 'discount2', 'discount3') if f in self.line._fields]
        before = {f: self.line[f] for f in fields}
        tax = self.env['account.tax'].create({'name': 'IVA F1', 'amount': 21, 'type_tax_use': 'sale'})
        self.line.tax_ids = tax
        taxes = self.line.tax_ids
        self.line.with_user(self.user).write(dict({f: 95 for f in fields}, tax_ids=[(6, 0, [])]))
        self.assertEqual({f: self.line[f] for f in fields}, before)
        self.assertEqual(self.line.tax_ids, taxes)
        fiscal = self.env['account.fiscal.position'].create({'name': 'Posición F1'})
        pricelist = self.env['product.pricelist'].create({'name': 'Tarifa F1'})
        old = (self.order.fiscal_position_id, self.order.pricelist_id)
        self.order.with_user(self.user).write({'fiscal_position_id': fiscal.id, 'pricelist_id': pricelist.id})
        self.assertEqual((self.order.fiscal_position_id, self.order.pricelist_id), old)

    def test_create_ignores_protected_fields(self):
        line = self.env['sale.order.line'].with_user(self.user).create({
            'order_id': self.order.id, 'product_id': self.product.id,
            'price_unit': 1, 'discount': 95,
        })
        self.assertEqual(line.price_unit, self.line.price_unit)
        self.assertEqual(line.discount, self.line.discount)

    def test_full_edit_and_actions(self):
        for action in ('action_update_prices', 'action_update_taxes', 'action_open_discount_wizard'):
            with self.assertRaises(AccessError):
                getattr(self.order.with_user(self.user), action)()
        self.user.group_ids |= self.env.ref('rms_ventas_restriccion_comerciales.group_comerciales_quotation_full_edit')
        self.line.with_user(self.user).write({'price_unit': 1, 'discount': 95, 'tax_ids': [(6, 0, [])]})
        self.assertEqual(self.line.price_unit, 1)
        self.assertEqual(self.line.discount, 95)
        self.assertFalse(self.line.tax_ids)
        fiscal = self.env['account.fiscal.position'].create({'name': 'Posición autorizada F1'})
        self.order.with_user(self.user).write({'fiscal_position_id': fiscal.id})
        self.assertEqual(self.order.fiscal_position_id, fiscal)
