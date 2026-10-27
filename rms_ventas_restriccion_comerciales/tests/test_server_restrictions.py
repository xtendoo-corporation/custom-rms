from lxml import etree

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
        cls.partner = cls.env['res.partner'].create({'name': 'Cliente F1', 'user_id': cls.user.id})
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

    def _protected_defaults(self):
        tax = self.env['account.tax'].create({
            'name': 'IVA contexto R1C', 'amount': 7, 'type_tax_use': 'sale',
        })
        fiscal = self.env['account.fiscal.position'].create({'name': 'Posición contexto R1C'})
        pricelist = self.env['product.pricelist'].create({'name': 'Tarifa contexto R1C'})
        defaults = {
            'default_price_unit': 1, 'default_discount': 95,
            'default_tax_ids': [(6, 0, tax.ids)],
            'default_pricelist_id': pricelist.id,
            'default_fiscal_position_id': fiscal.id,
        }
        for field in ('discount1', 'discount2', 'discount3'):
            if field in self.line._fields:
                defaults['default_' + field] = 95
        return defaults, tax, fiscal, pricelist

    def _assert_computed_line_values(self, line):
        for field in ('price_unit', 'discount', 'discount1', 'discount2', 'discount3', 'tax_ids'):
            if field in line._fields:
                self.assertEqual(line[field], self.line[field], field)

    def test_create_line_ignores_context_defaults(self):
        defaults, _tax, _fiscal, _pricelist = self._protected_defaults()
        line = self.env['sale.order.line'].with_user(self.user).with_context(defaults).create({
            'order_id': self.order.id, 'product_id': self.product.id,
        })
        self._assert_computed_line_values(line)

    def test_create_order_ignores_context_defaults_and_nested_lines(self):
        defaults, _tax, _fiscal, _pricelist = self._protected_defaults()
        order = self.env['sale.order'].with_user(self.user).with_context(defaults).create({
            'partner_id': self.partner.id, 'user_id': self.user.id,
            'order_line': [(0, 0, {'product_id': self.product.id})],
        })
        self.assertEqual(order.pricelist_id, self.order.pricelist_id)
        self.assertEqual(order.fiscal_position_id, self.order.fiscal_position_id)
        self.assertEqual(len(order.order_line), 1)
        self._assert_computed_line_values(order.order_line)

    def test_full_edit_preserves_context_defaults(self):
        self.user.group_ids |= self.env.ref(
            'rms_ventas_restriccion_comerciales.group_comerciales_quotation_full_edit'
        )
        defaults, tax, fiscal, pricelist = self._protected_defaults()
        # Evitar que el descuento triple recalcule el descuento global en esta prueba.
        for field in ('discount1', 'discount2', 'discount3'):
            defaults.pop('default_' + field, None)
        order = self.env['sale.order'].with_user(self.user).with_context(defaults).create({
            'partner_id': self.partner.id, 'user_id': self.user.id,
        })
        self.assertEqual(order.pricelist_id, pricelist)
        self.assertEqual(order.fiscal_position_id, fiscal)
        line = self.env['sale.order.line'].with_user(self.user).with_context(defaults).create({
            'order_id': order.id, 'product_id': self.product.id,
        })
        self.assertEqual(line.price_unit, 1)
        self.assertEqual(line.discount, 95)
        self.assertEqual(line.tax_ids, tax)

    def test_pricelist_group_keeps_pricelist_and_discounts(self):
        self.user.group_ids |= self.env.ref('rms_ventas_restriccion_comerciales.group_comerciales_pricelist')
        pricelist = self.env['product.pricelist'].create({
            'name': 'Tarifa tipo de cliente',
        })
        order = self.env['sale.order'].with_user(self.user).create({
            'partner_id': self.partner.id, 'user_id': self.user.id,
            'pricelist_id': pricelist.id,
            'order_line': [(0, 0, {'product_id': self.product.id})],
        })
        self.assertEqual(order.pricelist_id, pricelist)
        other = self.env['product.pricelist'].create({'name': 'Otra tarifa'})
        order.with_user(self.user).write({'pricelist_id': other.id})
        self.assertEqual(order.pricelist_id, other)
        order.with_user(self.user).action_update_prices()
        # Sigue sin poder tocar precios ni descuentos a mano.
        order.order_line.with_user(self.user).write({'discount': 50})
        self.assertNotEqual(order.order_line.discount, 50)
        with self.assertRaises(AccessError):
            order.with_user(self.user).action_update_taxes()

    def test_only_own_customers(self):
        other = self.env['res.partner'].create({'name': 'Cliente de otro comercial'})
        with self.assertRaises(ValidationError):
            self.env['sale.order'].with_user(self.user).create({'partner_id': other.id})
        with self.assertRaises(ValidationError):
            self.order.with_user(self.user).write({'partner_id': other.id})
        self.assertEqual(self.order.partner_id, self.partner)
        # Un contacto de la empresa de su cliente también es cliente suyo.
        contact = self.env['res.partner'].create({'name': 'Contacto F1', 'parent_id': self.partner.id})
        contact.user_id = False
        order = self.env['sale.order'].with_user(self.user).create({'partner_id': contact.id})
        self.assertEqual(order.partner_id, contact)
        # Otros usuarios de ventas no tienen esta restricción, ni los comerciales
        # con permiso para presupuestar a cualquier cliente.
        self.env['sale.order'].create({'partner_id': other.id})
        self.user.group_ids |= self.env.ref('rms_ventas_restriccion_comerciales.group_comerciales_all_customers')
        order = self.env['sale.order'].with_user(self.user).create({'partner_id': other.id})
        self.assertEqual(order.partner_id, other)

    def test_partner_dropdown_only_own_customers(self):
        arch = self.env['sale.order'].with_user(self.user).get_view(view_type='form')['arch']
        self.assertIn("('commercial_partner_id.user_id', '=', uid)", arch)
        arch = self.env['sale.order'].get_view(view_type='form')['arch']
        self.assertNotIn("('commercial_partner_id.user_id', '=', uid)", arch)
        self.user.group_ids |= self.env.ref('rms_ventas_restriccion_comerciales.group_comerciales_all_customers')
        arch = self.env['sale.order'].with_user(self.user).get_view(view_type='form')['arch']
        self.assertNotIn("('commercial_partner_id.user_id', '=', uid)", arch)

    def test_pricelist_readonly_without_pricelist_group(self):
        def pricelist_node():
            arch = self.env['sale.order'].with_user(self.user).get_view(view_type='form')['arch']
            return etree.fromstring(arch).xpath("//field[@name='pricelist_id']")[0]
        node = pricelist_node()
        self.assertEqual(node.get('readonly'), '1')
        self.assertNotEqual(node.get('invisible'), '1')
        self.user.group_ids |= self.env.ref('rms_ventas_restriccion_comerciales.group_comerciales_pricelist')
        self.assertNotEqual(pricelist_node().get('readonly'), '1')

    def test_order_takes_customer_pricelist(self):
        pricelist = self.env['product.pricelist'].create({'name': 'Tarifa del cliente'})
        self.partner.property_product_pricelist = pricelist
        order = self.env['sale.order'].with_user(self.user).create({'partner_id': self.partner.id})
        self.assertEqual(order.pricelist_id, pricelist)

    def test_lines_take_pricelist_triple_discount(self):
        if 'discount1' not in self.env['product.pricelist.item']._fields:
            self.skipTest('product_pricelist_triple_discount no instalado')
        pricelist = self.env['product.pricelist'].create({
            'name': 'Touring prueba',
            'item_ids': [(0, 0, {
                'applied_on': '3_global', 'compute_price': 'triple_discount',
                'discount1': 10, 'percent_price': 10, 'price_discount': 10,
            })],
        })
        self.partner.property_product_pricelist = pricelist
        order = self.env['sale.order'].with_user(self.user).create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {'product_id': self.product.id})],
        })
        line = order.order_line
        self.assertEqual(order.pricelist_id, pricelist)
        self.assertEqual(line.discount1, 10)
        self.assertAlmostEqual(line.price_subtotal, 90)
        line.with_user(self.user).write({'product_uom_qty': 2})
        self.assertEqual(line.discount1, 10)
        self.assertAlmostEqual(line.price_subtotal, 180)

    def test_discount_columns_visible_readonly(self):
        if 'discount1' not in self.env['sale.order.line']._fields:
            self.skipTest('sale_triple_discount no instalado')
        arch = self.env['sale.order'].with_user(self.user).get_view(view_type='form')['arch']
        nodes = etree.fromstring(arch).xpath("//field[@name='order_line']//list//field[@name='discount1']")
        self.assertTrue(nodes)
        self.assertEqual(nodes[0].get('readonly'), '1')
