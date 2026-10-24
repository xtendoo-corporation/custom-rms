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

    def test_summary_access(self):
        model = self.env["rms.training.user.summary"]
        with patch.object(type(model), "_refresh") as refresh:
            for user in (self.portal, self.internal):
                with self.assertRaises(AccessError):
                    model.with_user(user).action_open()
            refresh.assert_not_called()
        manager = new_test_user(self.env, login="s1_training", groups="base.group_user,rms_training_academy.group_training_manager")
        self.assertEqual(model.with_user(manager).action_open()["res_model"], "rms.training.user.summary")
        self.assertTrue(model.sudo().search([("user_id", "=", manager.id)]))
        self.assertEqual(model.with_user(self.portal).sudo().action_open()["res_model"], "rms.training.user.summary")
