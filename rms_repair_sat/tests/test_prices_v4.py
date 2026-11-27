from odoo import Command
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPricesV4(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env['stock.warehouse'].search([('company_id', '=', cls.env.company.id)], limit=1)
        cls.warehouse.code = 'RMS1'
        cls.env['stock.warehouse']._rms_setup_sat()
        cls.partner = cls.env['res.partner'].create({'name': 'Precio SAT'})
        cls.equipment = cls.env['product.product'].create({'name': 'Equipo SAT', 'is_storable': True})
        cls.part = cls.env['product.product'].create({'name': 'Pieza SAT', 'is_storable': True,
                                                       'tracking': 'serial', 'list_price': 1000, 'taxes_id': [Command.clear()]})
        cls.state = cls.env['product.state'].search([('code', '=', 'second_hand')], limit=1)
        cls.env['ir.config_parameter'].sudo().set_param('rms_repair_sat.parts_discount', '30')
        cls.env['ir.config_parameter'].sudo().set_param('rms_repair_sat.used_extra_discount', '50')

    def _quote(self, custom_price=0):
        lot = self.env['stock.lot'].create({'name': 'PIEZA-%s' % custom_price, 'product_id': self.part.id,
            'company_id': self.env.company.id, 'product_state_id': self.state.id, 'custom_price': custom_price})
        self.env['stock.quant']._update_available_quantity(self.part, self.warehouse.lot_stock_id, 1, lot_id=lot)
        repair = self.env['repair.order'].create({'partner_id': self.partner.id, 'product_id': self.equipment.id,
            'rms_site': 'madrid', 'move_ids': [Command.create({'product_id': self.part.id,
                'product_uom_qty': 1, 'repair_line_type': 'add'})]})
        repair.action_create_sale_order()
        return repair

    def test_parts_discounts_survive_quantity_change(self):
        repair = self._quote()
        original = repair.sale_order_id.order_line.filtered(lambda l: l.product_id == self.part and not l.rms_used_alternative_of_id)
        self.assertEqual((original.discount1, original.discount2), (30, 0))
        self.assertAlmostEqual(original.price_subtotal, 700)
        repair.action_rms_add_used_alternative()
        used = repair.sale_order_id.order_line.filtered('rms_used_alternative_of_id')
        self.assertEqual((used.price_unit, used.discount1, used.discount2), (1000, 30, 50))
        repair.action_rms_choose_used()
        self.assertEqual((used.discount1, used.discount2), (30, 50))
        self.assertAlmostEqual(used.price_subtotal, 350)

    def test_custom_used_price_has_no_discount(self):
        repair = self._quote(custom_price=420)
        repair.action_rms_add_used_alternative()
        used = repair.sale_order_id.order_line.filtered('rms_used_alternative_of_id')
        repair.action_rms_choose_used()
        self.assertEqual((used.price_unit, used.discount1, used.discount2, used.discount3), (420, 0, 0, 0))
        self.assertAlmostEqual(used.price_subtotal, 420)
