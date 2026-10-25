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
        cls.user = new_test_user(cls.env, login='f1_rms_ai_help_assistant', groups='base.group_user,sales_team.group_sale_salesman,custom.comerciales')
        cls.partner = cls.env['res.partner'].create({'name': 'Cliente F1'})
        cls.product = cls.env['product.product'].create({'name': 'Producto F1', 'list_price': 100})
        cls.order = cls.env['sale.order'].create({'partner_id': cls.partner.id, 'user_id': cls.user.id})
        cls.line = cls.env['sale.order.line'].create({'order_id': cls.order.id, 'product_id': cls.product.id})

    def test_hidden_pricelist_details(self):
        assistant = self.env['rms.ai.help.assistant'].with_user(self.user)
        rows = assistant._tool_buscar_cliente({'texto': self.partner.name})['resultados']
        self.assertTrue(rows)
        self.assertNotIn('lista_precios', rows[0])
        result = assistant._tool_consultar_precio_cliente({'cliente_id': self.partner.id, 'producto_id': self.product.id})
        self.assertNotIn('lista_precios', result)
        self.assertNotIn('descuentos_encadenados', result)
        self.assertIn('precio_final', result)
        group = self.env.ref('rms_ventas_restriccion_comerciales.group_comerciales_pricelist', raise_if_not_found=False)
        if group:
            self.user.group_ids |= group
            result = assistant._tool_consultar_precio_cliente({'cliente_id': self.partner.id, 'producto_id': self.product.id})
            self.assertIn('lista_precios', result)
