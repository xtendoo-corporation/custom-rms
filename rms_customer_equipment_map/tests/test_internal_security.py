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

    def test_map_without_maintenance_read_access(self):
        partner = self.env["res.partner"].create({
            "name": "F3 cliente sin mantenimiento", "partner_latitude": 40.4,
            "partner_longitude": -3.7,
        })
        self.env["maintenance.equipment"].create({
            "name": "F3 equipo privado", "partner_id": partner.id,
        })
        # Se retiran todas las concesiones para no depender de los grupos instalados.
        self.env["ir.model.access"].search([
            ("model_id", "=", self.env.ref("maintenance.model_maintenance_equipment").id),
            ("perm_read", "=", True),
        ]).write({"perm_read": False})
        Equipment = self.env["maintenance.equipment"].with_user(self.internal)
        self.assertFalse(Equipment.has_access("read"))
        rows = self.env["res.partner"].with_user(self.internal).get_customer_equipment_map_data()["partners"]
        row = next(row for row in rows if row["id"] == partner.id)
        self.assertEqual(row["equipment"], [])

    def test_map_equipment_respects_record_rules(self):
        partner = self.env["res.partner"].create({
            "name": "F3 cliente con equipo restringido", "partner_latitude": 40.4,
            "partner_longitude": -3.7,
        })
        equipment = self.env["maintenance.equipment"].create({
            "name": "F3 equipo restringido", "partner_id": partner.id,
        })
        allowed = self.env["maintenance.equipment"].create({
            "name": "F3 equipo permitido", "partner_id": partner.id,
        })
        # La regla estándar de mantenimiento exige seguir los equipos.
        # Ambos deben ser visibles antes de aplicar la restricción de este test.
        for item in equipment | allowed:
            item.message_subscribe(partner_ids=self.internal.partner_id.ids)
        Equipment = self.env["maintenance.equipment"].with_user(self.internal)
        self.assertTrue(Equipment.has_access("read"))
        self.assertEqual(
            Equipment.search([("partner_id", "=", partner.id)], order="id").ids,
            (equipment | allowed).ids,
        )
        self.env["ir.rule"].create({
            "name": "F3 ocultar equipo", "model_id": self.env.ref("maintenance.model_maintenance_equipment").id,
            "domain_force": "[('id', '!=', %s)]" % equipment.id,
        })
        self.assertEqual(
            Equipment.search([("partner_id", "=", partner.id)]).ids, allowed.ids,
        )
        rows = self.env["res.partner"].with_user(self.internal).get_customer_equipment_map_data()["partners"]
        row = next(row for row in rows if row["id"] == partner.id)
        self.assertEqual([item["id"] for item in row["equipment"]], allowed.ids)

    def test_map_equipment_respects_follower_rule(self):
        partner = self.env["res.partner"].create({
            "name": "F3 cliente con equipo seguido", "partner_latitude": 40.4,
            "partner_longitude": -3.7,
        })
        equipment = self.env["maintenance.equipment"].create({
            "name": "F3 equipo seguido", "partner_id": partner.id,
        })
        Equipment = self.env["maintenance.equipment"].with_user(self.internal)
        self.assertTrue(Equipment.has_access("read"))
        # La ACL permite leer, pero la regla estándar lo oculta hasta seguirlo.
        for follows in (False, True):
            with self.subTest(follows=follows):
                if follows:
                    equipment.message_subscribe(partner_ids=self.internal.partner_id.ids)
                expected_ids = equipment.ids if follows else []
                self.assertEqual(
                    Equipment.search([("partner_id", "=", partner.id)]).ids, expected_ids,
                )
                rows = self.env["res.partner"].with_user(self.internal).get_customer_equipment_map_data()["partners"]
                row = next(row for row in rows if row["id"] == partner.id)
                self.assertEqual([item["id"] for item in row["equipment"]], expected_ids)

    def test_map_hides_restricted_child_contact_details(self):
        partner = self.env["res.partner"].create({
            "name": "F3 empresa visible", "is_company": True,
            "partner_latitude": 40.4, "partner_longitude": -3.7,
        })
        contact = self.env["res.partner"].create({
            "name": "F3 persona restringida", "parent_id": partner.id,
            "email": "privado@example.com", "phone": "123456789",
        })
        self.env["ir.rule"].create({
            "name": "F3 ocultar contacto hijo", "model_id": self.env.ref("base.model_res_partner").id,
            "domain_force": "[('id', '!=', %s)]" % contact.id,
        })
        rows = self.env["res.partner"].with_user(self.internal).get_customer_equipment_map_data()["partners"]
        row = next(row for row in rows if row["id"] == partner.id)
        self.assertEqual(row["contact_name"], "")
        self.assertEqual(row["email"], "")
        self.assertEqual(row["phone"], "")
