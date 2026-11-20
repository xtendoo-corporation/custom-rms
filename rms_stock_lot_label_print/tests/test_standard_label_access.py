import json

from odoo.tests import TransactionCase, new_test_user, tagged
from ..hooks import uninstall_hook


@tagged('post_install', '-at_install')
class TestStandardLabelAccess(TransactionCase):
    def test_standard_labels_hidden_from_stock_user(self):
        user = new_test_user(self.env, login='lot_label_access_v2', groups='stock.group_stock_user')
        reports = self.env['ir.actions.actions'].with_user(user).get_bindings('stock.lot').get('report', [])
        ids = {report['id'] for report in reports}
        self.assertNotIn(self.env.ref('stock.action_report_lot_label').id, ids)
        self.assertNotIn(self.env.ref('stock.label_lot_template').id, ids)
        self.assertIn(self.env.ref('rms_stock_lot_label_print.action_report_lot_label_10x5').id, ids)

    def test_uninstall_restores_saved_groups(self):
        params = self.env['ir.config_parameter'].sudo()
        group = self.env.ref('stock.group_stock_user')
        for xmlid in ('stock.action_report_lot_label', 'stock.label_lot_template'):
            params.set_param('rms_stock_lot_label_print.original_groups.' + xmlid, json.dumps([group.id]))
        uninstall_hook(self.env)
        for xmlid in ('stock.action_report_lot_label', 'stock.label_lot_template'):
            self.assertEqual(self.env.ref(xmlid).group_ids, group)
