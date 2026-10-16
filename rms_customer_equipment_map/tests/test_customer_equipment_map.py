from odoo.tests.common import TransactionCase, new_test_user


class TestCustomerEquipmentMap(TransactionCase):
    def test_map_data_works_without_partner_equipment_model_import(self):
        map_user = new_test_user(
            self.env,
            login="customer_equipment_map_user",
            groups="base.group_user",
        )
        partner = self.env["res.partner"].create(
            {
                "name": "Cliente geolocalizado",
                "is_company": True,
                "partner_latitude": 40.4168,
                "partner_longitude": -3.7038,
                "user_id": map_user.id,
            }
        )
        map_data = (
            self.env["res.partner"]
            .with_user(map_user)
            .get_customer_equipment_map_data()
        )
        partner_data = next(
            item for item in map_data["partners"] if item["id"] == partner.id
        )

        self.assertEqual(partner_data["id"], partner.id)

    def test_map_data_respects_record_rules(self):
        map_user = new_test_user(
            self.env,
            login="customer_equipment_map_user_rules",
            groups="base.group_user",
        )
        partner_allowed = self.env["res.partner"].create(
            {
                "name": "Cliente permitido",
                "partner_latitude": 40.4168,
                "partner_longitude": -3.7038,
            }
        )
        partner_restricted = self.env["res.partner"].create(
            {
                "name": "Cliente restringido",
                "partner_latitude": 41.3874,
                "partner_longitude": 2.1686,
            }
        )

        # Create a record rule to restrict partners for base.group_user
        rule = self.env["ir.rule"].create(
            {
                "name": "Test Partner Rule",
                "model_id": self.env.ref("base.model_res_partner").id,
                "domain_force": "[('name', '=', 'Cliente permitido')]",
                "groups": [(4, self.env.ref("base.group_user").id)],
            }
        )

        try:
            map_data = (
                self.env["res.partner"]
                .with_user(map_user)
                .get_customer_equipment_map_data()
            )
            partner_ids = [item["id"] for item in map_data["partners"]]
            self.assertIn(partner_allowed.id, partner_ids)
            self.assertNotIn(partner_restricted.id, partner_ids)
            self.assertFalse(map_data["is_admin"])
        finally:
            rule.unlink()

    def test_map_data_admin_returns_all_geolocated_partners(self):
        admin_user = new_test_user(
            self.env,
            login="customer_equipment_map_admin",
            groups="base.group_user,base.group_system",
        )
        first_partner = self.env["res.partner"].create(
            {
                "name": "Cliente uno",
                "partner_latitude": 40.4168,
                "partner_longitude": -3.7038,
            }
        )
        second_partner = self.env["res.partner"].create(
            {
                "name": "Cliente dos",
                "partner_latitude": 41.3874,
                "partner_longitude": 2.1686,
            }
        )

        map_data = (
            self.env["res.partner"]
            .with_user(admin_user)
            .get_customer_equipment_map_data()
        )

        partner_ids = {item["id"] for item in map_data["partners"]}
        self.assertIn(first_partner.id, partner_ids)
        self.assertIn(second_partner.id, partner_ids)
        self.assertTrue(map_data["is_admin"])

    def test_map_data_geolocation_group_without_system_admin(self):
        geolocation_user = new_test_user(
            self.env,
            login="customer_equipment_map_geolocation_user",
            groups="base.group_user,"
            "rms_customer_equipment_map.group_customer_equipment_map_geolocation",
        )
        self.assertFalse(geolocation_user.has_group("base.group_system"))

        first_partner = self.env["res.partner"].create(
            {
                "name": "Cliente uno",
                "partner_latitude": 40.4168,
                "partner_longitude": -3.7038,
            }
        )
        second_partner = self.env["res.partner"].create(
            {
                "name": "Cliente dos",
                "partner_latitude": 41.3874,
                "partner_longitude": 2.1686,
            }
        )

        map_data = (
            self.env["res.partner"]
            .with_user(geolocation_user)
            .get_customer_equipment_map_data()
        )

        partner_ids = {item["id"] for item in map_data["partners"]}
        self.assertIn(first_partner.id, partner_ids)
        self.assertIn(second_partner.id, partner_ids)
        self.assertTrue(map_data["is_admin"])

        # Can also see the geolocation summary and the list of failing
        # addresses, and relaunch them, without being a Settings admin.
        candidate = self.env["res.partner"].create(
            {
                "name": "Cliente con dirección pendiente",
                "street": "Calle Falsa 123",
            }
        )
        self.assertEqual(candidate.geo_localize_state, "pending")

        Partner = self.env["res.partner"].with_user(geolocation_user)
        summary = Partner.get_geo_localize_summary()
        self.assertGreaterEqual(summary["pending"], 1)

        action = Partner.action_view_geo_localize_partners("pending")
        self.assertIn(("geo_localize_state", "=", "pending"), action["domain"])

        candidate.geo_localize_state = "failed"
        candidate.with_user(geolocation_user).action_geo_localize_retry()
        self.assertEqual(candidate.geo_localize_state, "pending")

    def test_map_data_uses_contact_person_phone_and_email(self):
        company = self.env["res.partner"].create(
            {
                "name": "Teatro sin teléfono",
                "is_company": True,
                "partner_latitude": 40.4168,
                "partner_longitude": -3.7038,
            }
        )
        self.env["res.partner"].create(
            [
                {"name": "Sin datos", "parent_id": company.id, "type": "contact"},
                {
                    "name": "Facturación",
                    "parent_id": company.id,
                    "type": "invoice",
                    "phone": "+34 900 000 001",
                },
                {
                    "name": "Ana Técnica",
                    "parent_id": company.id,
                    "type": "contact",
                    "phone": "+34 600 111 222",
                    "email": "ana@teatro.es",
                },
            ]
        )
        own = self.env["res.partner"].create(
            {
                "name": "Teatro con datos",
                "is_company": True,
                "phone": "+34 954 000 000",
                "email": "info@teatro2.es",
                "partner_latitude": 37.38,
                "partner_longitude": -5.98,
            }
        )
        self.env["res.partner"].create(
            {
                "name": "Otra persona",
                "parent_id": own.id,
                "type": "contact",
                "phone": "+34 600 999 999",
            }
        )
        data = {
            item["id"]: item
            for item in self.env["res.partner"].get_customer_equipment_map_data()["partners"]
        }
        self.assertEqual(data[company.id]["phone"], "+34 600 111 222")
        self.assertEqual(data[company.id]["email"], "ana@teatro.es")
        self.assertEqual(data[company.id]["contact_name"], "Ana Técnica")
        self.assertEqual(data[own.id]["phone"], "+34 954 000 000")
        self.assertEqual(data[own.id]["email"], "info@teatro2.es")
        self.assertEqual(data[own.id]["contact_name"], "")
