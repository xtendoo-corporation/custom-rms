from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user

from odoo.addons.rms_ventas_restriccion_comerciales.models.restrictions import (
    lock_prices_and_taxes,
)


@tagged('post_install', '-at_install')
class TestRewardLines(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not cls.env.ref('custom.comerciales', raise_if_not_found=False):
            group = cls.env['res.groups'].create({'name': 'Comerciales prueba promociones'})
            cls.env['ir.model.data'].create({
                'module': 'custom', 'name': 'comerciales',
                'model': 'res.groups', 'res_id': group.id,
            })
        # Mismo escenario de contactos propios que las restricciones de ventas.
        if not cls.env['ir.rule'].search_count([
            ('model_id', '=', cls.env.ref('base.model_res_partner').id),
            ('name', '=', 'CUSTOM/Contactos propios'),
        ]):
            cls.env['ir.rule'].create({
                'name': 'CUSTOM/Contactos propios (prueba promociones)',
                'model_id': cls.env.ref('base.model_res_partner').id,
                'groups': [(6, 0, cls.env.ref('custom.comerciales').ids)],
                'domain_force': "['|', ('user_id', '=', user.id), ('user_ids', '!=', False)]",
                'perm_read': True, 'perm_write': True,
                'perm_create': True, 'perm_unlink': False,
            })
        cls.comercial = new_test_user(
            cls.env, login='rms_sale_loyalty_comercial',
            groups='base.group_user,sales_team.group_sale_salesman,custom.comerciales',
        )
        cls.manager = new_test_user(
            cls.env, login='rms_sale_loyalty_manager',
            groups='base.group_user,sales_team.group_sale_manager',
        )
        cls.partner = cls.env['res.partner'].create({
            'name': 'Cliente promociones propio', 'user_id': cls.comercial.id,
        })
        cls.trigger = cls.env['product.product'].create({
            'name': 'Disparador promociones RMS', 'list_price': 100, 'taxes_id': [(5, 0, 0)],
        })
        cls.free = cls.env['product.product'].create({
            'name': 'Flight case regalo RMS', 'list_price': 80, 'taxes_id': [(5, 0, 0)],
        })
        cls.pricelist = cls.env['product.pricelist'].create({'name': 'Tarifa promociones RMS'})
        cls.program = cls.env['loyalty.program'].create({
            'name': 'Compra dos y recibe flight case RMS',
            'program_type': 'buy_x_get_y', 'trigger': 'auto', 'applies_on': 'current',
            'rule_ids': [(0, 0, {
                'product_ids': [(6, 0, cls.trigger.ids)], 'minimum_qty': 2,
                'reward_point_amount': 1, 'reward_point_mode': 'unit',
            })],
            'reward_ids': [(0, 0, {
                'reward_type': 'product', 'reward_product_id': cls.free.id,
                'reward_product_qty': 1, 'required_points': 2,
            })],
        })
        cls.reward = cls.program.reward_ids

    def _order(self, user, pricelist=None):
        self.partner.property_product_pricelist = pricelist or self.pricelist
        return self.env['sale.order'].with_user(user).create({
            'partner_id': self.partner.id, 'user_id': user.id,
            'order_line': [(0, 0, {'product_id': self.trigger.id, 'product_uom_qty': 2})],
        })

    def _apply_reward(self, order):
        order._update_programs_and_rewards()
        for coupon, rewards in order._get_claimable_rewards().items():
            self.assertFalse(order._apply_program_reward(rewards[:1], coupon))
        order._update_programs_and_rewards()
        self._assert_free(order)

    def _assert_free(self, order, qty=1):
        lines = order.order_line.filtered('is_reward_line')
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines.product_id.id, self.free.id)
        self.assertEqual(lines.reward_id.id, self.reward.id)
        self.assertEqual(lines.product_uom_qty, qty)
        self.assertEqual((lines.discount1, lines.discount2, lines.discount3), (100, 0, 0))
        self.assertEqual(lines.discount, 100)
        self.assertAlmostEqual(lines.price_subtotal, 0)
        return lines

    def _assert_stable(self, order):
        for _ in range(3):
            order._update_programs_and_rewards()
            self._assert_free(order)

    def _triple_pricelist(self):
        return self.env['product.pricelist'].create({
            'name': 'Tarifa triple promociones RMS',
            'item_ids': [(0, 0, {
                'applied_on': '3_global', 'compute_price': 'triple_discount',
                'discount1': 30, 'discount2': 10,
                'percent_price': 30, 'price_discount': 30,
            })],
        })

    def test_reward_stable_and_quantity_increases(self):
        order = self._order(self.manager)
        self._apply_reward(order)
        self._assert_stable(order)
        order.order_line.filtered(lambda line: not line.is_reward_line).write({
            'product_uom_qty': 4,
        })
        order._update_programs_and_rewards()
        self._assert_free(order, qty=2)

    def test_triple_pricelist_and_update_prices(self):
        order = self._order(self.manager, self._triple_pricelist())
        self._apply_reward(order)
        self._assert_stable(order)
        normal = order.order_line.filtered(lambda line: not line.is_reward_line)
        self.assertEqual((normal.discount1, normal.discount2, normal.discount3), (30, 10, 0))
        order.action_update_prices()
        self.assertEqual((normal.discount1, normal.discount2, normal.discount3), (30, 10, 0))
        self._assert_free(order)

    def test_restricted_comercial_reward_and_manual_write(self):
        self.assertTrue(lock_prices_and_taxes(self.env(user=self.comercial)))
        order = self._order(self.comercial, self._triple_pricelist())
        self.assertFalse(order.env.su)
        self._apply_reward(order)
        self._assert_stable(order)
        line = self._assert_free(order)
        price_unit = line.price_unit
        line.write({'discount': 0, 'price_unit': 1})
        self.assertEqual(line.price_unit, price_unit)
        self._assert_free(order)

    def test_comercial_cannot_forge_reward(self):
        order = self._order(self.comercial)
        vals = {
            'order_id': order.id, 'product_id': self.free.id, 'product_uom_qty': 5,
            'reward_id': self.reward.id, 'discount': 100,
            'points_cost': 2, 'reward_identifier_code': 'forjado',
        }
        line = self.env['sale.order.line'].with_user(self.comercial).create(vals)
        self.assertFalse(line.reward_id)
        self.assertFalse(line.points_cost)
        self.assertFalse(line.reward_identifier_code)
        self.assertGreater(line.price_subtotal, 0)
        normal = order.order_line.filtered(lambda item: item.product_id.id == self.trigger.id)
        normal.write({'reward_id': self.reward.id})
        self.assertFalse(normal.reward_id)
        # Las claves de contexto tampoco deben abrir una vía alternativa.
        line = self.env['sale.order.line'].with_user(self.comercial).with_context(
            default_reward_id=self.reward.id, default_points_cost=2,
            default_reward_identifier_code='forjado-contexto',
            force_pricelist_discounts=True,
        ).create({'order_id': order.id, 'product_id': self.free.id, 'product_uom_qty': 5})
        self.assertFalse(line.reward_id)
        self.assertFalse(line.points_cost)
        self.assertFalse(line.reward_identifier_code)
        self.assertGreater(line.price_subtotal, 0)

    def test_comercial_program_timezone(self):
        order = self._order(self.comercial)
        self.env.company.partner_id.tz = 'Europe/Madrid'
        self.assertEqual(order.with_user(self.comercial)._get_program_timezone(), 'Europe/Madrid')
        self.env.company.partner_id.tz = False
        self.env['ir.config_parameter'].sudo().set_param('loyalty.timezone', 'UTC')
        self.assertEqual(order.with_user(self.comercial)._get_program_timezone(), 'UTC')
