from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSatNoticeV4(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({'name': 'Cliente avisos v4'})
        cls.product = cls.env['product.product'].create({'name': 'Equipo avisos v4'})

    def _repair(self):
        return self.env['repair.order'].create({'partner_id': self.customer.id,
                                                'product_id': self.product.id})

    def test_return_shipping_default_and_legacy_options(self):
        params = self.env['ir.config_parameter'].sudo()
        params.search([('key', '=', 'rms_repair_sat.default_return_shipping')]).unlink()
        repair = self._repair()
        self.assertEqual(repair.rms_return_shipping, 'invoice')
        for option in ('invoice', 'collect', 'customer', 'hand', 'ours'):
            repair.rms_return_shipping = option
            self.assertEqual(repair.rms_return_shipping_effective, option)
        repair.write({'under_warranty': True, 'rms_return_shipping': 'invoice'})
        self.assertEqual(repair.rms_return_shipping_effective, 'ours')
        params.set_param('rms_repair_sat.default_return_shipping', 'customer')
        self.assertEqual(self._repair().rms_return_shipping, 'customer')

    def test_late_waiting_part_and_factory_are_only_informative(self):
        repair = self._repair()
        repair.action_rms_wait_part()
        repair.rms_stage_date = fields.Datetime.now() - timedelta(days=31, minutes=1)
        repair.invalidate_recordset(['rms_late'])
        self.assertTrue(repair.rms_late)
        repair.action_rms_part_received()
        self.assertEqual(repair.rms_stage, 'repair')
        repair.rms_stage = 'factory'
        repair.rms_stage_date = fields.Datetime.now() - timedelta(days=31, minutes=1)
        repair.invalidate_recordset(['rms_late'])
        self.assertTrue(repair.rms_late)
        action = repair.action_rms_back_from_factory()
        self.assertEqual(action['res_model'], 'rms.repair.factory.return.wizard')
