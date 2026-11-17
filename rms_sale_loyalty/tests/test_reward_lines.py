from lxml import etree

from odoo.exceptions import AccessError, ValidationError
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

    def test_comercial_cannot_change_existing_gift(self):
        order = self._order(self.comercial)
        self._apply_reward(order)
        gift = self._assert_free(order)
        gift.write({'product_uom_qty': 50})
        self._assert_free(order)
        order.with_user(self.comercial).write({
            'order_line': [(1, gift.id, {'product_uom_qty': 50})],
        })
        self._assert_free(order)
        gift.write({'product_id': self.trigger.id})
        self._assert_free(order)

    def test_comercial_can_increase_trigger_quantity(self):
        order = self._order(self.comercial)
        self._apply_reward(order)
        normal = order.order_line.filtered(lambda line: not line.is_reward_line)
        # Una escritura mixta solo debe filtrar la cantidad del regalo.
        order.order_line.write({'product_uom_qty': 4})
        self.assertEqual(normal.product_uom_qty, 4)
        self._assert_free(order)
        order._update_programs_and_rewards()
        self._assert_free(order, qty=2)

    def test_comercial_can_unlink_gift(self):
        order = self._order(self.comercial)
        self._apply_reward(order)
        gift = self._assert_free(order)
        gift.unlink()
        self.assertFalse(gift.exists())

    def test_manager_can_change_existing_gift(self):
        order = self._order(self.manager)
        self._apply_reward(order)
        gift = self._assert_free(order)
        self.assertFalse(gift.env.su)
        gift.write({'product_uom_qty': 50})
        self._assert_free(order, qty=50)
        gift.write({'product_id': self.trigger.id})
        self.assertEqual(gift.product_id, self.trigger)
        self.assertAlmostEqual(gift.price_subtotal, 0)

    def test_comercial_cannot_update_rewards_from_another_order(self):
        order = self._order(self.comercial)
        other_order = self._order(self.comercial)
        self._apply_reward(other_order)
        gift = self._assert_free(other_order)
        with self.assertRaises(AccessError):
            order._write_vals_from_reward_vals([], gift)
        self._assert_free(other_order)

    def test_comercial_program_timezone(self):
        order = self._order(self.comercial)
        self.env.company.partner_id.tz = 'Europe/Madrid'
        self.assertEqual(order.with_user(self.comercial)._get_program_timezone(), 'Europe/Madrid')
        self.env.company.partner_id.tz = False
        self.env['ir.config_parameter'].sudo().set_param('loyalty.timezone', 'UTC')
        self.assertEqual(order.with_user(self.comercial)._get_program_timezone(), 'UTC')

    def _reward_wizard(self, order):
        order.action_open_reward_wizard()
        return self.env['sale.loyalty.reward.wizard'].with_user(order.env.user).with_context(
            active_id=order.id,
        ).create({})

    def _second_gift_program(self, order):
        trigger = self.env['product.product'].create({
            'name': 'Segundo disparador RMS', 'list_price': 100, 'taxes_id': [(5, 0, 0)],
        })
        gift = self.env['product.product'].create({
            'name': 'Segundo regalo RMS', 'list_price': 80, 'taxes_id': [(5, 0, 0)],
        })
        program = self.env['loyalty.program'].create({
            'name': 'Segunda promoción RMS',
            'rms_internal_note': 'Nota comercial segunda promoción',
            'program_type': 'buy_x_get_y', 'trigger': 'auto', 'applies_on': 'current',
            'rule_ids': [(0, 0, {
                'product_ids': [(6, 0, trigger.ids)], 'minimum_qty': 2,
                'reward_point_amount': 1, 'reward_point_mode': 'unit',
            })],
            'reward_ids': [(0, 0, {
                'reward_type': 'product', 'reward_product_id': gift.id,
                'reward_product_qty': 1, 'required_points': 2,
            })],
        })
        order.write({'order_line': [(0, 0, {
            'product_id': trigger.id, 'product_uom_qty': 2,
        })]})
        return program

    def test_reward_action_always_opens_without_applying(self):
        order = self._order(self.manager)
        action = order.action_open_reward_wizard()
        self.assertIsInstance(action, dict)
        self.assertEqual(action['res_model'], 'sale.loyalty.reward.wizard')
        self.assertEqual(action['name'], 'Promociones disponibles')
        # La ventana llega ya creada, con una línea por promoción reclamable.
        wizard = self.env['sale.loyalty.reward.wizard'].browse(action['res_id'])
        self.assertEqual(wizard.order_id, order)
        self.assertEqual(wizard.line_ids.reward_id, self.reward)
        rewards = self.env['loyalty.reward']
        for claimable in order._get_claimable_rewards().values():
            rewards |= claimable
        self.assertEqual(rewards, self.reward)
        self.assertFalse(order.order_line.filtered('reward_id'))
        order.order_line.write({'product_uom_qty': 1})
        action = order.action_open_reward_wizard()
        self.assertIsInstance(action, dict)
        self.assertEqual(action['res_model'], 'sale.loyalty.reward.wizard')
        self.assertFalse(order._get_claimable_rewards())
        self.assertFalse(order.order_line.filtered('reward_id'))

    def test_wizard_lists_notes_and_applies_both_selected_gifts(self):
        self.program.rms_internal_note = 'No comunicar al cliente'
        order = self._order(self.manager)
        second = self._second_gift_program(order)
        wizard = self._reward_wizard(order)
        expected = self.env['loyalty.reward']
        for rewards in order._get_claimable_rewards().values():
            expected |= rewards
        self.assertEqual(len(wizard.line_ids), len(expected))
        self.assertEqual(wizard.line_ids.reward_id, self.reward | second.reward_ids)
        for line in wizard.line_ids:
            self.assertEqual(line.internal_note, line.program_id.rms_internal_note)
        wizard.line_ids.write({'selected': True})
        wizard.action_apply()
        gifts = order.order_line.filtered('reward_id')
        self.assertEqual(len(gifts), 2)
        self.assertEqual(gifts.reward_id, self.reward | second.reward_ids)
        for gift in gifts:
            self.assertAlmostEqual(gift.price_subtotal, 0, places=2)

    def test_wizard_applies_only_selected_gift(self):
        order = self._order(self.manager)
        self._second_gift_program(order)
        wizard = self._reward_wizard(order)
        self.assertEqual(len(wizard.line_ids), 2)
        wizard.line_ids.filtered(lambda line: line.reward_id == self.reward).selected = True
        wizard.action_apply()
        self._assert_free(order)

    def test_wizard_requires_selection_and_can_be_empty(self):
        order = self._order(self.manager)
        wizard = self._reward_wizard(order)
        self.assertTrue(wizard.line_ids)
        self.assertFalse(wizard.line_ids.filtered('selected'))
        with self.assertRaisesRegex(ValidationError, 'Selecciona al menos una promoción.'):
            wizard.action_apply()
        order.order_line.write({'product_uom_qty': 1})
        self.assertFalse(self._reward_wizard(order).line_ids)

    def test_wizard_respects_program_pricelists(self):
        other_pricelist = self.env['product.pricelist'].create({'name': 'Otra tarifa RMS'})
        self.program.pricelist_ids = other_pricelist
        order = self._order(self.manager)
        self.assertEqual(order.pricelist_id, self.pricelist)
        self.assertFalse(self._reward_wizard(order).line_ids)
        self.program.pricelist_ids = self.pricelist
        self.assertEqual(self._reward_wizard(order).line_ids.reward_id, self.reward)

    def _discount_program(self):
        self.program.active = False
        return self.env['loyalty.program'].create({
            'name': 'Diez por ciento RMS',
            'program_type': 'promotion', 'trigger': 'auto', 'applies_on': 'current',
            'rule_ids': [(0, 0, {
                'product_ids': [(6, 0, self.trigger.ids)], 'minimum_qty': 2,
                'reward_point_amount': 1, 'reward_point_mode': 'order',
            })],
            'reward_ids': [(0, 0, {
                'reward_type': 'discount', 'discount': 10,
                'discount_mode': 'percent', 'discount_applicability': 'order',
                'required_points': 1,
            })],
        })

    def _assert_order_discount(self, order, reward):
        normal = order.order_line.filtered(lambda line: not line.reward_id)
        self.assertTrue(normal)
        for line in normal:
            self.assertEqual((line.discount1, line.discount2, line.discount3), (30, 10, 0))
        lines = order.order_line.filtered(lambda line: line.reward_id == reward)
        self.assertTrue(lines)
        for line in lines:
            self.assertEqual((line.discount1, line.discount2, line.discount3, line.discount),
                             (0, 0, 0, 0))
        self.assertAlmostEqual(sum(lines.mapped('price_subtotal')),
                               -0.1 * sum(normal.mapped('price_subtotal')), places=2)
        return lines

    def test_percentage_reward_with_triple_discount(self):
        program = self._discount_program()
        order = self._order(self.manager, self._triple_pricelist())
        wizard = self._reward_wizard(order)
        self.assertEqual(wizard.line_ids.reward_id, program.reward_ids)
        wizard.line_ids.selected = True
        wizard.action_apply()
        self._assert_order_discount(order, program.reward_ids)
        for _ in range(3):
            order._update_programs_and_rewards()
            self._assert_order_discount(order, program.reward_ids)

    def test_comercial_percentage_reward_and_protected_values(self):
        program = self._discount_program()
        order = self._order(self.comercial, self._triple_pricelist())
        self.assertFalse(order.env.su)
        wizard = self._reward_wizard(order)
        self.assertFalse(wizard.env.su)
        self.assertEqual(wizard.line_ids.reward_id, program.reward_ids)
        wizard.line_ids.selected = True
        wizard.action_apply()
        lines = self._assert_order_discount(order, program.reward_ids)
        for line in lines:
            qty, price = line.product_uom_qty, line.price_unit
            line.write({'product_uom_qty': 50})
            self.assertEqual(line.product_uom_qty, qty)
            line.write({'price_unit': -999})
            self.assertEqual(line.price_unit, price)
        for _ in range(3):
            order._update_programs_and_rewards()
            self._assert_order_discount(order, program.reward_ids)

    def test_promotion_buttons_for_all_users(self):
        coupon_action = self.env.ref('sale_loyalty.sale_loyalty_coupon_wizard_action').id
        for model in (self.env['sale.order'], self.env['sale.order'].with_user(self.comercial)):
            with self.subTest(user=model.env.user.login):
                arch = etree.fromstring(model.get_view(view_type='form')['arch'])
                for name in (str(coupon_action), 'action_open_discount_wizard'):
                    buttons = arch.xpath('//button[@name="%s"]' % name)
                    # Odoo quita de la vista los botones de «Descuento» a quien
                    # no tiene el grupo de descuentos en líneas.
                    self.assertIn(len(buttons), (2,) if name != 'action_open_discount_wizard' else (0, 2))
                    for button in buttons:
                        self.assertIn(button.get('invisible'), ('1', 'True'))
                rewards = arch.xpath('//button[@name="action_open_reward_wizard"]')
                self.assertEqual(len(rewards), 2)
                for button in rewards:
                    self.assertEqual(button.get('string'), 'Promociones')
