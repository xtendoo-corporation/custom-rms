from odoo.tests.common import TransactionCase, new_test_user


class TestCustomerEquipmentMap(TransactionCase):
    def test_map_data_includes_partner_equipment_models(self):
        equipment_model = self.env["equipment.model.tag"].create(
            {"name": "GALAXY 816"}
        )
        partner = self.env["res.partner"].create(
            {
                "name": "Cliente geolocalizado",
                "is_company": True,
                "partner_latitude": 40.4168,
                "partner_longitude": -3.7038,
                "equipment_model_tag_ids": [(4, equipment_model.id)],
            }
        )

        map_user = new_test_user(
            self.env,
            login="customer_equipment_map_user",
            groups="base.group_user",
        )
        map_data = (
            self.env["res.partner"]
            .with_user(map_user)
            .get_customer_equipment_map_data()
        )
        partner_data = next(
            item for item in map_data if item["id"] == partner.id
        )

        self.assertEqual(
            partner_data["equipment_models"],
            [{"id": equipment_model.id, "name": "GALAXY 816"}],
        )
