import json

from odoo.tests import TransactionCase, new_test_user, tagged
from ..dedup_hooks import uninstall_hook


@tagged('post_install', '-at_install')
class TestStandardAccess(TransactionCase):
    def test_menu_and_print_visibility(self):
        user = new_test_user(self.env, login='sat_access_v2',
                             groups='stock.group_stock_user,repair_security.group_repair_user')
        menu = self.env.ref('repair.menu_repair_order')
        self.assertFalse(menu.with_user(user)._filter_visible_menus())
        self.assertTrue(self.env.ref('rms_repair_sat.menu_rms_sat_root').with_user(user)._filter_visible_menus())
        reports = self.env['ir.actions.actions'].with_user(user).get_bindings('repair.order').get('report', [])
        ids = {report['id'] for report in reports}
        self.assertNotIn(self.env.ref('repair.action_report_repair_order').id, ids)
        for xmlid in ('rms_repair_sat.action_report_receipt', 'rms_repair_sat.action_report_pickup',
                      'rms_repair_sat.action_report_label_equipment', 'rms_repair_sat.action_report_label_bag'):
            self.assertIn(self.env.ref(xmlid).id, ids)

    def test_uninstall_restores_saved_groups(self):
        param = self.env['ir.config_parameter'].sudo()
        old_group = self.env.ref('stock.group_stock_user')
        targets = ('repair.menu_repair_order', 'repair.action_report_repair_order')
        for xmlid in targets:
            param.set_param('rms_repair_sat.original_groups.' + xmlid, json.dumps([old_group.id]))
        uninstall_hook(self.env)
        for xmlid in targets:
            self.assertEqual(self.env.ref(xmlid).group_ids, old_group)
