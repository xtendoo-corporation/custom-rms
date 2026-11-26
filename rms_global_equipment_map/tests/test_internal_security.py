import base64
import io
import json
from types import SimpleNamespace
from unittest.mock import patch

import openpyxl

from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import HttpCase, TransactionCase, new_test_user

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


@tagged("post_install", "-at_install")
class TestMapCompanySecurity(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env["res.company"].create({"name": "F3 compañía A"})
        cls.company_b = cls.env["res.company"].create({"name": "F3 compañía B"})
        cls.user = new_test_user(
            cls.env, login="f3_global_company_a", groups="base.group_user",
            company_id=cls.company_a.id, company_ids=[(6, 0, cls.company_a.ids)],
        )
        cls.partners = cls.env["res.partner"].create([
            {"name": "F3 cliente A", "company_id": cls.company_a.id,
             "partner_latitude": 40.4, "partner_longitude": -3.7},
            {"name": "F3 cliente B", "company_id": cls.company_b.id,
             "partner_latitude": 41.4, "partner_longitude": 2.1},
        ])

    def _request(self):
        return patch(
            "odoo.addons.rms_global_equipment_map.controllers.main.request",
            SimpleNamespace(env=self.env["res.partner"].with_user(self.user).with_context(
                allowed_company_ids=self.company_a.ids,
            ).env),
        )

    def test_map_respects_company_rules(self):
        with self._request():
            rows = GlobalEquipmentMapController().get_global_equipment_map_partners()
        ids = {row["id"] for row in rows}
        self.assertIn(self.partners[0].id, ids)
        self.assertNotIn(self.partners[1].id, ids)

    def test_export_filters_arbitrary_partner_ids(self):
        with self._request():
            result = GlobalEquipmentMapController().export_global_equipment_map_xlsx(
                self.partners.ids,
            )
        workbook = openpyxl.load_workbook(io.BytesIO(base64.b64decode(result["content"])))
        names = [row[0] for row in workbook.active.iter_rows(min_row=2, values_only=True)]
        self.assertEqual(names, [self.partners[0].name])

    def test_map_hides_restricted_child_contact_details(self):
        contact = self.env["res.partner"].create({
            "name": "F3 contacto privado", "parent_id": self.partners[0].id,
            "email": "privado@example.com", "phone": "123456789",
        })
        self.env["ir.rule"].create({
            "name": "F3 ocultar contacto hijo", "model_id": self.env.ref("base.model_res_partner").id,
            "domain_force": "[('id', '!=', %s)]" % contact.id,
        })
        with self._request():
            rows = GlobalEquipmentMapController().get_global_equipment_map_partners()
        row = next(row for row in rows if row["id"] == self.partners[0].id)
        self.assertEqual(row["contact_name"], "")
        self.assertEqual(row["email"], "")
        self.assertEqual(row["phone"], "")


@tagged("post_install", "-at_install")
class TestMapAllPartnersSecurity(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env["res.company"].create({"name": "Mapa todos compañía A"})
        cls.company_b = cls.env["res.company"].create({"name": "Mapa todos compañía B"})
        company_values = {
            "company_id": cls.company_a.id,
            "company_ids": [(6, 0, cls.company_a.ids)],
        }
        cls.internal = new_test_user(
            cls.env, login="map_all_internal", groups="base.group_user", **company_values,
        )
        cls.all_partners_user = new_test_user(
            cls.env, login="map_all_privileged",
            groups="base.group_user,rms_global_equipment_map.group_map_all_partners",
            **company_values,
        )
        cls.portal = new_test_user(cls.env, login="map_all_portal", groups="base.group_portal")
        cls.partners = cls.env["res.partner"].create([
            {"name": "Mapa cliente oculto", "company_id": cls.company_a.id,
             "partner_latitude": 40.4, "partner_longitude": -3.7},
            {"name": "Mapa cliente otra compañía", "company_id": cls.company_b.id,
             "partner_latitude": 41.4, "partner_longitude": 2.1},
        ])
        cls.env["ir.rule"].create({
            "name": "Mapa ocultar cliente", "model_id": cls.env.ref("base.model_res_partner").id,
            "domain_force": "[('id', '!=', %s)]" % cls.partners[0].id,
        })

    def _request(self, user):
        return patch(
            "odoo.addons.rms_global_equipment_map.controllers.main.request",
            SimpleNamespace(env=self.env["res.partner"].with_user(user).with_context(
                allowed_company_ids=self.company_a.ids,
            ).env),
        )

    def test_restricted_partner_requires_group(self):
        with self._request(self.internal):
            rows = GlobalEquipmentMapController().get_global_equipment_map_partners()
        self.assertNotIn(self.partners[0].id, [row["id"] for row in rows])

    def test_group_sees_and_exports_restricted_partner_in_allowed_company(self):
        with self._request(self.all_partners_user):
            controller = GlobalEquipmentMapController()
            rows = controller.get_global_equipment_map_partners()
            result = controller.export_global_equipment_map_xlsx(self.partners.ids)
        ids = {row["id"] for row in rows}
        self.assertIn(self.partners[0].id, ids)
        self.assertNotIn(self.partners[1].id, ids)
        workbook = openpyxl.load_workbook(io.BytesIO(base64.b64decode(result["content"])))
        names = [row[0] for row in workbook.active.iter_rows(min_row=2, values_only=True)]
        self.assertEqual(names, [self.partners[0].name])

    def test_portal_is_denied(self):
        with self._request(self.portal):
            controller = GlobalEquipmentMapController()
            with self.assertRaises(AccessError):
                controller.get_global_equipment_map_partners()
            with self.assertRaises(AccessError):
                controller.export_global_equipment_map_xlsx(self.partners.ids)


@tagged("post_install", "-at_install")
class TestMapSalespersonSecurity(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        values = {"company_id": cls.company.id, "company_ids": [(6, 0, cls.company.ids)]}
        cls.internal = new_test_user(cls.env, login="map_sales_internal", groups="base.group_user", **values)
        cls.privileged = new_test_user(
            cls.env, login="map_sales_all", groups="base.group_user,rms_global_equipment_map.group_map_all_partners", **values,
        )
        cls.system = new_test_user(cls.env, login="map_sales_system", groups="base.group_user,base.group_system", **values)
        cls.salesperson = new_test_user(cls.env, login="map_sales_person", groups="base.group_user", **values)
        cls.partner = cls.env["res.partner"].create({
            "name": "Mapa cliente comercial", "company_id": cls.company.id,
            "partner_latitude": 40.4, "partner_longitude": -3.7,
            "user_id": cls.salesperson.id,
        })

    def _request(self, user):
        return patch(
            "odoo.addons.rms_global_equipment_map.controllers.main.request",
            SimpleNamespace(env=self.env["res.partner"].with_user(user).with_context(
                allowed_company_ids=self.company.ids,
            ).env),
        )

    def _read_and_export(self, user):
        with self._request(user):
            controller = GlobalEquipmentMapController()
            rows = controller.get_global_equipment_map_partners()
            result = controller.export_global_equipment_map_xlsx([self.partner.id])
        row = next(row for row in rows if row["id"] == self.partner.id)
        sheet = openpyxl.load_workbook(io.BytesIO(base64.b64decode(result["content"]))).active
        return row, sheet

    def test_internal_cannot_see_salesperson(self):
        row, sheet = self._read_and_export(self.internal)
        self.assertNotIn("salesperson", row)
        self.assertNotIn("Comercial", [cell.value for cell in sheet[1]])

    def test_all_partners_user_sees_salesperson(self):
        row, sheet = self._read_and_export(self.privileged)
        self.assertEqual(row["salesperson"], {"id": self.salesperson.id, "name": self.salesperson.name})
        self.assertEqual(sheet.cell(1, 2).value, "Comercial")
        self.assertEqual(sheet.cell(2, 2).value, self.salesperson.name)

    def test_system_user_sees_salesperson(self):
        row, sheet = self._read_and_export(self.system)
        self.assertEqual(row["salesperson"], {"id": self.salesperson.id, "name": self.salesperson.name})
        self.assertEqual(sheet.cell(1, 2).value, "Comercial")
        self.assertEqual(sheet.cell(2, 2).value, self.salesperson.name)
