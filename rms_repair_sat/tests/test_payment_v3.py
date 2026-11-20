from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestSatPayment(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({'name': 'Pago SAT'})
        cls.service = cls.env['product.product'].create({'name': 'Servicio SAT prueba', 'type': 'service', 'list_price': 100})
        cls.warehouse = cls.env['stock.warehouse'].search([('company_id', '=', cls.env.company.id)], limit=1)
        cls.warehouse.code = 'RMS1'
        cls.env['stock.warehouse']._rms_setup_sat()
        cls.product = cls.env['product.product'].create({'name': 'Equipo SAT pago', 'is_storable': True, 'tracking': 'serial'})

    def _repair(self):
        order = self.env['sale.order'].create({'partner_id': self.customer.id,
            'order_line': [Command.create({'product_id': self.service.id, 'product_uom_qty': 1, 'price_unit': 100})]})
        repair = self.env['repair.order'].create({'partner_id': self.customer.id, 'product_id': self.product.id,
                                                  'rms_site': 'madrid', 'sale_order_id': order.id})
        return repair

    def test_payment_gate_and_single_override(self):
        repair = self._repair()
        self.assertFalse(repair.rms_paid)
        with self.assertRaisesRegex(UserError, 'Falta el cobro'):
            repair._rms_check_payment()
        repair.action_rms_force_payment()
        repair._rms_check_payment()
        repair._rms_consume_payment_force()
        with self.assertRaisesRegex(UserError, 'Falta el cobro'):
            repair._rms_check_payment()
        repair.rms_owner_type = 'company'
        repair._rms_check_payment()
        repair.rms_owner_type = 'customer'
        repair.under_warranty = True
        repair._rms_check_payment()

    def test_pay_later_and_risk_exception(self):
        repair = self._repair()
        self.customer.rms_sat_pay_later = True
        repair.invalidate_recordset()
        self.assertTrue(repair.rms_payment_exempt)
        self.customer.rms_sat_no_risk_limit = True
        repair.invalidate_recordset()
        self.assertEqual(repair.rms_payment_exempt_reason, 'Sin límite ni riesgo')
        self.assertFalse(repair.rms_has_risk_limit)

    def test_fields_restricted_and_force_manager_only(self):
        user = new_test_user(self.env, login='sat_payment_worker', groups='rms_repair_sat.group_sat_warehouse')
        with self.assertRaises(AccessError):
            self.customer.with_user(user).write({'rms_sat_pay_later': True})
        repair = self._repair()
        with self.assertRaises(AccessError):
            repair.with_user(user).action_rms_force_payment()
        with self.assertRaises(AccessError):
            repair.with_user(user).with_context(rms_payment_consume=True).write({'rms_payment_forced': True})

    def test_zero_order_paid_and_confirmation_activity_no_duplicate(self):
        repair = self._repair()
        repair.sale_order_id.order_line.price_unit = 0
        repair.invalidate_recordset()
        self.assertTrue(repair.rms_paid)
        repair.sale_order_id.order_line.price_unit = 100
        repair.invalidate_recordset()
        repair.sale_order_id.action_confirm()
        repair._rms_schedule_admin_activity('payment')
        activities = self.env['mail.activity'].search([('res_model', '=', 'repair.order'),
            ('res_id', '=', repair.id), ('summary', '=', 'Cobrar la reparación %s antes de empezar' % repair.name)])
        self.assertEqual(len(activities), 1)
