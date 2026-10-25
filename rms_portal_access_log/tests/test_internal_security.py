from unittest.mock import patch

from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged("post_install", "-at_install")
class TestInternalSecurity(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.portal = new_test_user(cls.env, login="s1_portal", groups="base.group_portal")
        cls.internal = new_test_user(cls.env, login="s1_internal", groups="base.group_user")

    def test_send_now_access(self):
        model = self.env["rms.portal.weekly.report"]
        with patch.object(type(model), "_send_report") as send:
            with self.assertRaises(AccessError):
                model.with_user(self.portal).action_send_now()
            send.assert_not_called()
            with self.assertRaises(AccessError):
                model.with_user(self.internal).action_send_now()
            self.internal.group_ids |= self.env.ref("rms_portal_access_log.group_portal_weekly_report")
            self.assertEqual(model.with_user(self.internal).action_send_now()["tag"], "display_notification")
            send.assert_called_once()
            model.with_user(self.portal).sudo().action_send_now()

    def test_cron_still_sends(self):
        model = self.env["rms.portal.weekly.report"].sudo()
        self.env["ir.config_parameter"].sudo().set_param("rms_portal_access_log.last_weekly_report_date", "")
        with patch.object(type(model), "_get_recipients", return_value=self.internal), patch.object(type(model), "_send_report") as send:
            model._cron_send_weekly_report()
            send.assert_called_once_with(self.internal)
            model._cron_send_weekly_report()
            send.assert_called_once_with(self.internal)
