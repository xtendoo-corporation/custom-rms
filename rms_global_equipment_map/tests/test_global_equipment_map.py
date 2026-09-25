from odoo.tests.common import TransactionCase, new_test_user


class TestGlobalEquipmentMap(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Partner = cls.env["res.partner"]
        cls.tag = cls.env["equipment.model.tag"].create({"name": "Mesa de mezclas X32"})
        cls.allowed = cls.Partner.create(
            {
                "name": "Cliente permitido",
                "is_company": True,
                "partner_latitude": 40.4168,
                "partner_longitude": -3.7038,
                "equipment_model_tag_ids": [(6, 0, cls.tag.ids)],
            }
        )
        cls.restricted = cls.Partner.create(
            {
                "name": "Cliente restringido",
                "is_company": True,
                "partner_latitude": 41.3874,
                "partner_longitude": 2.1686,
            }
        )
        cls.env["ir.rule"].create(
            {
                "name": "Test global map partner rule",
                "model_id": cls.env.ref("base.model_res_partner").id,
                "domain_force": "[('name', '!=', 'Cliente restringido')]",
                "groups": [(4, cls.env.ref("base.group_user").id)],
            }
        )
        cls.user = new_test_user(
            cls.env, login="global_map_user", groups="base.group_user"
        )
        cls.admin = new_test_user(
            cls.env,
            login="global_map_admin",
            groups="base.group_user,base.group_system",
        )

    def test_user_only_sees_allowed_partners(self):
        data = self.Partner.with_user(self.user).get_global_equipment_map_partners()
        partner_ids = {item["id"] for item in data}
        self.assertIn(self.allowed.id, partner_ids)
        self.assertNotIn(self.restricted.id, partner_ids)
        allowed_data = next(item for item in data if item["id"] == self.allowed.id)
        self.assertEqual(
            allowed_data["equipment_models"],
            [{"id": self.tag.id, "name": self.tag.display_name}],
        )

    def test_user_cannot_export_restricted_partner_by_id(self):
        data = self.Partner.with_user(self.user).get_global_equipment_map_partners(
            [self.allowed.id, self.restricted.id]
        )
        self.assertEqual([item["id"] for item in data], [self.allowed.id])

    def test_admin_sees_all_partners(self):
        data = self.Partner.with_user(self.admin).get_global_equipment_map_partners(
            [self.allowed.id, self.restricted.id]
        )
        self.assertEqual(
            {item["id"] for item in data}, {self.allowed.id, self.restricted.id}
        )
