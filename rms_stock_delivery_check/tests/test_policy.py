from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tests.common import new_test_user

from .common import DeliveryCheckCommon


@tagged('post_install', '-at_install')
class TestCheckRequiredOnlySerial(DeliveryCheckCommon):
    """Checklist obligatorio solo con nº de serie y salto de un responsable."""

    def setUp(self):
        super().setUp()
        self.warehouse.out_type_id.rms_check_required = True

    def _skip(self, picking, reason, user=None):
        wizard = self.env['rms.check.skip.wizard'].with_user(user or self.manager).create({
            'picking_id': picking.id, 'reason': reason})
        return wizard.action_confirm()

    def test_required_with_serial_blocks(self):
        self._lot(self.galaxy, 'POL-A')
        picking = self._picking([(self.galaxy, 1), (self.cover, 2)])
        self.assertTrue(picking.rms_check_mandatory)
        with self.assertRaisesRegex(UserError, 'checklist'):
            picking.with_user(self.operator).button_validate()
        self.assertNotEqual(picking.state, 'done')

    def test_only_quantity_is_free(self):
        picking = self._picking([(self.cover, 2)])
        self.assertFalse(picking.rms_check_mandatory)
        picking.with_user(self.operator).button_validate()
        self.assertEqual(picking.state, 'done')

    def test_off_by_default(self):
        self.warehouse.out_type_id.rms_check_required = False
        self._lot(self.galaxy, 'POL-B')
        picking = self._picking([(self.galaxy, 1)])
        self.assertFalse(picking.rms_check_mandatory)
        picking.with_user(self.operator).button_validate()
        self.assertEqual(picking.state, 'done')

    def test_manager_skip_with_reason_in_history(self):
        self._lot(self.galaxy, 'POL-C')
        picking = self._picking([(self.galaxy, 1)])
        with self.assertRaises(UserError):
            picking.with_user(self.manager)._rms_validate_skipping_check('   ')
        self.assertNotEqual(picking.state, 'done')
        self._skip(picking, 'Pistola sin batería')
        self.assertEqual(picking.state, 'done')
        body = ' '.join(picking.message_ids.mapped('body'))
        self.assertIn('Pistola sin batería', body)
        self.assertIn(self.manager.name, body)
        self.assertIn('SIN checklist', body)

    def test_operator_cannot_skip(self):
        self._lot(self.galaxy, 'POL-D')
        picking = self._picking([(self.galaxy, 1)])
        with self.assertRaises(AccessError):
            picking.with_user(self.operator).action_rms_skip_check()
        with self.assertRaises(AccessError):
            picking.with_user(self.operator)._rms_validate_skipping_check('quiero')
        self.assertNotEqual(picking.state, 'done')
        # el botón solo lo ve el responsable
        view = self.env['stock.picking'].with_user(self.operator).get_view(
            self.env.ref('stock.view_picking_form').id)
        self.assertNotIn('action_rms_skip_check', view['arch'])
        view = self.env['stock.picking'].with_user(self.manager).get_view(
            self.env.ref('stock.view_picking_form').id)
        self.assertIn('action_rms_skip_check', view['arch'])


@tagged('post_install', '-at_install')
class TestDepositAlert(DeliveryCheckCommon):

    def setUp(self):
        super().setUp()
        self.salesman = new_test_user(
            self.env, login='c2_comercial', groups='base.group_user',
            company_id=self.company.id, company_ids=[Command.set(self.company.ids)])
        self.partner.user_id = self.salesman
        self.deposit = self._out_deposit()

    def _out_deposit(self):
        self._lot(self.galaxy, 'ALR-A')
        Cession = self.env['stock.cession'].with_user(self.operator)
        defaults = Cession.default_get(['location_src_id', 'location_dest_id', 'company_id'])
        deposit = Cession.create(dict(defaults, partner_id=self.partner.id, rms_line_ids=[
            Command.create({'product_id': self.galaxy.id, 'quantity': 1})]))
        deposit.action_rms_prepare_out()
        out = deposit.picking_id
        self._scan(out, 'ALR-A')
        out.with_user(self.operator).rms_check_finish()
        out.with_user(self.operator).rms_check_validate()
        self.assertEqual(deposit.rms_deposit_state, 'out')
        return deposit

    def _age(self, days):
        units = self.deposit.rms_unit_ids.sudo()
        units.write({'date_out': fields.Datetime.now() - timedelta(days=days)})
        units.invalidate_recordset()
        self.deposit.invalidate_recordset()

    def _alerts(self):
        return self.env['mail.activity'].sudo().search([
            ('res_model', '=', 'stock.cession'), ('res_id', '=', self.deposit.id),
            ('activity_type_id', '=', self.env.ref('rms_stock_delivery_check.mail_activity_type_deposit_long').id)])

    def test_no_alert_before_days(self):
        self._age(29)
        self.env['stock.cession']._cron_rms_deposit_alerts()
        self.assertFalse(self._alerts())
        self.assertFalse(self.deposit.rms_deposit_overdue)

    def test_alert_to_salesman_once_and_again_after_close(self):
        self._age(31)
        self.assertTrue(self.deposit.rms_deposit_overdue)
        self.assertEqual(self.env['stock.cession'].search([('rms_deposit_overdue', '=', True)]), self.deposit)
        self.env['stock.cession']._cron_rms_deposit_alerts()
        alerts = self._alerts()
        self.assertEqual(alerts.user_id, self.salesman)
        self.assertEqual(len(alerts), 1)
        self.assertIn('30 días', alerts.summary)
        # no se repite mientras siga abierta
        self.env['stock.cession']._cron_rms_deposit_alerts()
        self.assertEqual(len(self._alerts()), 1)
        # cerrada: no avisa hasta pasados otros N días
        alerts.action_done()
        self.env['stock.cession']._cron_rms_deposit_alerts()
        self.assertFalse(self._alerts())
        self.deposit.rms_alert_date = fields.Datetime.now() - timedelta(days=31)
        self.env['stock.cession']._cron_rms_deposit_alerts()
        self.assertEqual(self._alerts().user_id, self.salesman)

    def test_fallback_creator_and_configured_manager(self):
        self.partner.user_id = False
        self._age(40)
        self.env['stock.cession']._cron_rms_deposit_alerts()
        self.assertEqual(self._alerts().user_id, self.deposit.create_uid)
        self._alerts().unlink()
        self.deposit.rms_alert_date = False
        self.company.rms_deposit_manager_id = self.manager
        self.env['stock.cession']._cron_rms_deposit_alerts()
        self.assertEqual(self._alerts().user_id, self.deposit.create_uid | self.manager)

    def test_configurable_days_and_returned_deposit(self):
        self.env['ir.config_parameter'].set_param('rms_stock_delivery_check.deposit_alert_days', '60')
        self._age(40)
        self.env['stock.cession']._cron_rms_deposit_alerts()
        self.assertFalse(self._alerts())
        self.env['ir.config_parameter'].set_param('rms_stock_delivery_check.deposit_alert_days', '15')
        self.env['stock.cession']._cron_rms_deposit_alerts()
        self.assertEqual(len(self._alerts()), 1)
        self.assertIn('15 días', self._alerts().summary)

    def test_returned_deposit_not_alerted(self):
        self._age(40)
        self.deposit.rms_unit_ids.sudo().write({'state': 'returned', 'date_return': fields.Datetime.now()})
        self.env['stock.cession']._cron_rms_deposit_alerts()
        self.assertFalse(self._alerts())
