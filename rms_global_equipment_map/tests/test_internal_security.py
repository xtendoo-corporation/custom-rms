import base64
import io
import json
from unittest.mock import patch

import openpyxl

from odoo.tests import tagged
from odoo.tests.common import HttpCase, new_test_user

from odoo.addons.rms_global_equipment_map.controllers.main import GlobalEquipmentMapController


@tagged("post_install", "-at_install")
class TestMapRouteSecurity(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.portal = new_test_user(cls.env, login="s1_map_portal", password="s1-password", groups="base.group_portal")
        cls.internal = new_test_user(cls.env, login="s1_map_internal", password="s1-password", groups="base.group_user")
        cls.partner = cls.env["res.partner"].create({
            "name": "S1 cliente del mapa", "partner_latitude": 40.4,
            "partner_longitude": -3.7,
        })

    def _post(self, path, params):
        response = self.url_open(
            path,
            data=json.dumps({"jsonrpc": "2.0", "method": "call", "params": params, "id": 1}),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_portal_denied_before_read(self):
        self.authenticate(self.portal.login, "s1-password")
        with patch.object(GlobalEquipmentMapController, "_read_partners") as read:
            for path in ("partners", "export_xlsx"):
                with self.subTest(route=path):
                    result = self._post("/rms_global_equipment_map/" + path, {})
                    self.assertNotIn("result", result)
                    self.assertEqual(result["error"]["data"]["name"], "odoo.exceptions.AccessError")
            read.assert_not_called()

    def test_internal_can_read_and_export(self):
        self.authenticate(self.internal.login, "s1-password")
        result = self._post("/rms_global_equipment_map/partners", {})
        self.assertNotIn("error", result)
        self.assertIn(self.partner.id, [row["id"] for row in result["result"]])
        result = self._post("/rms_global_equipment_map/export_xlsx", {"partner_ids": [self.partner.id]})
        self.assertNotIn("error", result)
        workbook = openpyxl.load_workbook(io.BytesIO(base64.b64decode(result["result"]["content"])))
        self.assertEqual(workbook.active.cell(2, 1).value, self.partner.name)
