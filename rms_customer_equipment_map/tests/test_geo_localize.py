from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, new_test_user

from odoo.addons.rms_customer_equipment_map.models import res_partner as res_partner_module


class TestGeoLocalize(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Partner = cls.env["res.partner"]
        cls.spain = cls.env.ref("base.es")
        # Isolate the tests from the partners already present in the database.
        cls.Partner.search(
            [("geo_localize_state", "in", ("pending", "failed"))]
        ).write({"active": False})

    def setUp(self):
        super().setUp()
        # No real waiting nor real commits during the tests.
        self.patch(res_partner_module.time, "sleep", lambda seconds: None)
        self.patch(
            type(self.env["ir.cron"]),
            "_commit_progress",
            lambda self, processed=0, remaining=None, deactivate=False: float("inf"),
        )

    def _create_partner(self, **vals):
        return self.Partner.create(
            {"name": "Cliente", "city": "Sevilla", "country_id": self.spain.id, **vals}
        )

    def _patch_geo_localize(self, side_effect):
        return patch.object(
            type(self.Partner), "_geo_localize", autospec=True, side_effect=side_effect
        )

    def test_state_follows_coordinates_and_address(self):
        partner = self._create_partner()
        self.assertEqual(partner.geo_localize_state, "pending")

        partner.write({"partner_latitude": 37.38, "partner_longitude": -5.98})
        self.assertEqual(partner.geo_localize_state, "done")

        # base_geolocalize resets the coordinates when the address changes, so
        # the contact must go back to the queue instead of vanishing from the map.
        partner.write({"city": "Cádiz"})
        self.assertFalse(partner.partner_latitude)
        self.assertEqual(partner.geo_localize_state, "pending")

        no_address = self.Partner.create({"name": "Sin dirección"})
        self.assertEqual(no_address.geo_localize_state, "no_address")

    def test_address_change_schedules_the_cron_once(self):
        cron = self.env.ref("rms_customer_equipment_map.ir_cron_geo_localize_partners")
        triggers = self.env["ir.cron.trigger"].search([("cron_id", "=", cron.id)])
        self._create_partner(name="Uno")
        self._create_partner(name="Dos")
        self.env.cr.precommit.run()
        new_triggers = (
            self.env["ir.cron.trigger"].search([("cron_id", "=", cron.id)]) - triggers
        )
        self.assertEqual(len(new_triggers), 1)

    def test_cron_geolocates_pending_partners(self):
        partner = self._create_partner()
        with self._patch_geo_localize(lambda *args: (37.38, -5.98)):
            self.Partner._cron_geo_localize_partners()
        self.assertEqual(partner.geo_localize_state, "done")
        self.assertEqual(partner.partner_latitude, 37.38)
        self.assertEqual(partner.partner_longitude, -5.98)
        self.assertTrue(partner.date_localization)
        self.assertTrue(partner.geo_localize_last_try)

    def test_cron_retries_failed_partners_with_backoff(self):
        partner = self._create_partner()
        with self._patch_geo_localize(lambda *args: None) as geo_localize:
            self.Partner._cron_geo_localize_partners()
            self.assertEqual(partner.geo_localize_state, "failed")
            self.assertEqual(partner.geo_localize_attempts, 1)
            self.assertTrue(partner.geo_localize_error)

            # Not retried before the back-off delay has elapsed.
            self.Partner._cron_geo_localize_partners()
            self.assertEqual(geo_localize.call_count, 1)

            partner.geo_localize_last_try = fields.Datetime.now() - timedelta(days=2)
            self.Partner._cron_geo_localize_partners()
            self.assertEqual(geo_localize.call_count, 2)
            self.assertEqual(partner.geo_localize_attempts, 2)

            # Abandoned after the last retry.
            partner.write(
                {
                    "geo_localize_attempts": len(res_partner_module.GEO_LOCALIZE_RETRY_DAYS) + 1,
                    "geo_localize_last_try": fields.Datetime.now() - timedelta(days=365),
                }
            )
            self.assertNotIn(partner, self.Partner._get_geo_localize_due_partners())

        # Fixing the address puts the contact back in the queue.
        partner.write({"street": "Calle Sierpes 1"})
        self.assertEqual(partner.geo_localize_state, "pending")
        self.assertEqual(partner.geo_localize_attempts, 0)

    def test_cron_stops_on_repeated_service_errors(self):
        partners = self.Partner.browse(
            [self._create_partner(name=f"Cliente {index}").id for index in range(5)]
        )

        def service_down(*args):
            raise UserError("Error with geolocation server: timeout")

        with self._patch_geo_localize(service_down) as geo_localize:
            self.Partner._cron_geo_localize_partners()
        self.assertEqual(
            geo_localize.call_count, res_partner_module.GEO_LOCALIZE_MAX_SERVICE_ERRORS
        )
        # Service errors do not consume retries: contacts stay pending.
        self.assertEqual(set(partners.mapped("geo_localize_state")), {"pending"})
        self.assertEqual(set(partners.mapped("geo_localize_attempts")), {0})

    def test_enqueue_requeues_failed_partners(self):
        admin = new_test_user(
            self.env,
            login="customer_map_geo_admin",
            groups="base.group_user,base.group_system",
        )
        partner = self._create_partner()
        partner.write(
            {
                "geo_localize_state": "failed",
                "geo_localize_attempts": 2,
                "geo_localize_last_try": fields.Datetime.now(),
            }
        )
        result = self.Partner.with_user(admin).action_enqueue_geo_localize()
        self.assertEqual(result["count"], 1)
        self.assertEqual(partner.geo_localize_state, "pending")
        self.assertIn(partner, self.Partner._get_geo_localize_due_partners())

    def test_enqueue_requires_admin(self):
        user = new_test_user(
            self.env, login="customer_map_geo_user", groups="base.group_user"
        )
        with self.assertRaises(UserError):
            self.Partner.with_user(user).action_enqueue_geo_localize()
