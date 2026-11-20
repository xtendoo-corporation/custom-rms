from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSatNotifications(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({'name': 'Cliente avisos', 'email': 'cliente@example.test'})
        cls.contact = cls.env['res.partner'].create({'name': 'Contacto avisos', 'parent_id': cls.customer.id,
                                                      'email': 'contacto@example.test'})
        cls.product = cls.env['product.product'].create({'name': 'Equipo avisos', 'type': 'consu'})

    def _repair(self):
        return self.env['repair.order'].create({'partner_id': self.customer.id, 'rms_contact_id': self.contact.id,
                                                'product_id': self.product.id, 'rms_site': 'madrid'})

    def test_ready_mail_once_per_entry(self):
        repair = self._repair()
        template_model = type(self.env['mail.template'])
        with patch.object(template_model, 'send_mail', autospec=True) as send_mail:
            repair.write({'rms_stage': 'ready'})
            self.assertEqual(repair.rms_ready_date, fields.Date.context_today(repair))
            self.assertEqual(send_mail.call_count, 1)
            self.assertEqual(send_mail.call_args.kwargs['email_values']['email_to'], self.contact.email)
            repair.write({'rms_stage': 'ready'})
            self.assertEqual(send_mail.call_count, 1)
            repair.write({'rms_stage': 'repair'})
            repair.write({'rms_stage': 'ready'})
            self.assertEqual(send_mail.call_count, 2)

    def test_ready_mail_when_odoo_state_changes(self):
        repair = self._repair()
        with patch.object(type(self.env['mail.template']), 'send_mail', autospec=True) as send_mail:
            repair.write({'state': 'done'})
            self.assertEqual(repair.rms_stage, 'ready')
            self.assertEqual(send_mail.call_count, 1)
            self.assertTrue(repair.rms_ready_date)

    def test_reminders_sent_once_and_activity_created(self):
        repair = self._repair()
        template_model = type(self.env['mail.template'])
        with patch.object(template_model, 'send_mail', autospec=True) as send_mail:
            repair.write({'rms_stage': 'ready'})
            send_mail.reset_mock()
            repair.rms_ready_date = fields.Date.context_today(repair) - timedelta(days=91)
            self.env['repair.order']._cron_rms_pickup_reminders()
            self.assertTrue(repair.rms_reminder_1_sent)
            self.assertTrue(repair.rms_reminder_2_sent)
            self.assertTrue(repair.rms_not_collected)
            self.assertEqual(send_mail.call_count, 2)
            activities = self.env['mail.activity'].search([
                ('res_model', '=', 'repair.order'), ('res_id', '=', repair.id),
                ('summary', '=', 'Equipo sin recoger %s' % repair.name)])
            self.assertTrue(activities)
            self.env['repair.order']._cron_rms_pickup_reminders()
            self.assertEqual(send_mail.call_count, 2)
            self.assertEqual(activities, self.env['mail.activity'].search([
                ('res_model', '=', 'repair.order'), ('res_id', '=', repair.id),
                ('summary', '=', 'Equipo sin recoger %s' % repair.name)]))

    def test_rejected_date_drives_reminder(self):
        repair = self._repair()
        repair.write({'rms_stage': 'uncollected',
                      'rms_rejected_date': fields.Date.context_today(repair) - timedelta(days=61)})
        with patch.object(type(self.env['mail.template']), 'send_mail', autospec=True) as send_mail:
            self.env['repair.order']._cron_rms_pickup_reminders()
            self.assertEqual(send_mail.call_count, 2)
            self.assertTrue(repair.rms_reminder_1_sent)
            self.assertTrue(repair.rms_reminder_2_sent)
            self.assertFalse(repair.rms_not_collected)

    def test_shipping_line_and_warranty(self):
        repair = self._repair()
        order = self.env['sale.order'].create({'partner_id': self.customer.id})
        repair.write({'sale_order_id': order.id, 'rms_return_shipping': 'invoice'})
        repair.action_rms_add_shipping()
        repair.action_rms_add_shipping()
        self.assertEqual(len(order.order_line), 1)
        self.assertEqual(order.order_line.product_id, self.env.ref('rms_repair_sat.product_sat_shipping'))
        self.assertEqual(order.order_line.price_unit, 0)
        order.order_line.price_unit = 20
        repair.under_warranty = True
        self.assertEqual(order.order_line.price_unit, 0)
        self.assertEqual(repair.rms_return_shipping_effective, 'ours')
        with self.assertRaises(UserError):
            repair.action_rms_add_shipping()
