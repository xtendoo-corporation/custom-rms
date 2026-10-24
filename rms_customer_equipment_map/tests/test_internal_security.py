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

    def test_map_access(self):
        model = self.env["res.partner"]
        with self.assertRaises(AccessError):
            model.with_user(self.portal).get_customer_equipment_map_data()
        self.assertIn("partners", model.with_user(self.internal).get_customer_equipment_map_data())
        self.assertIn("partners", model.with_user(self.portal).sudo().get_customer_equipment_map_data())

    def test_geolocation_access(self):
        model = self.env["res.partner"]
        calls = [("get_geo_localize_summary", ()), ("action_view_geo_localize_partners", ("pending",)),
                 ("action_geo_localize_retry", ()), ("action_enqueue_geo_localize", ()),
                 ("action_geo_localize_batch", ())]
        for user in (self.portal, self.internal):
            for method, args in calls:
                with self.subTest(user=user.login, method=method), self.assertRaises(AccessError):
                    getattr(model.with_user(user), method)(*args)
        manager = new_test_user(self.env, login="s1_geo", groups="base.group_user,rms_customer_equipment_map.group_customer_equipment_map_geolocation")
        model = model.with_user(manager)
        self.assertIn("pending", model.get_geo_localize_summary())
        self.assertEqual(model.action_view_geo_localize_partners("pending")["res_model"], "res.partner")
        self.assertEqual(model.action_geo_localize_retry()["type"], "ir.actions.client")
        self.assertIn("count", model.action_enqueue_geo_localize())
        # Avoid contacting the external geolocation service.
        with patch.object(type(model), "_get_geo_localize_pause_seconds", return_value=60):
            self.assertTrue(model.action_geo_localize_batch()["service_error"])
