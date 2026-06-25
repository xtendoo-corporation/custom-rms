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
            item for item in map_data if item["id"] == partner.id
        )

        self.assertEqual(partner_data["id"], partner.id)

    def test_map_data_only_returns_current_salesperson_partners(self):
        map_user = new_test_user(
            self.env,
            login="customer_equipment_map_salesperson",
            groups="base.group_user",
        )
        other_user = new_test_user(
            self.env,
            login="customer_equipment_map_other_salesperson",
            groups="base.group_user",
        )
        assigned_partner = self.env["res.partner"].create(
            {
                "name": "Cliente asignado",
                "partner_latitude": 40.4168,
                "partner_longitude": -3.7038,
                "user_id": map_user.id,
            }
        )
        self.env["res.partner"].create(
            {
                "name": "Cliente de otro comercial",
                "partner_latitude": 41.3874,
                "partner_longitude": 2.1686,
                "user_id": other_user.id,
            }
        )

        map_data = (
            self.env["res.partner"]
            .with_user(map_user)
            .get_customer_equipment_map_data()
        )

        self.assertEqual([item["id"] for item in map_data], [assigned_partner.id])


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

        partner_ids = {item["id"] for item in map_data}
        self.assertIn(first_partner.id, partner_ids)
        self.assertIn(second_partner.id, partner_ids)
