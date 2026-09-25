from datetime import timedelta
from unittest.mock import MagicMock, patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, new_test_user

from odoo.addons.rms_customer_equipment_map.models import nominatim
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
        self.patch(nominatim.time, "sleep", lambda seconds: None)
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

    def test_failed_error_explains_address_and_missing_parts(self):
        partner = self._create_partner(street="Calle Inventada 99")
        with self._patch_geo_localize(lambda *args: None):
            self.Partner._cron_geo_localize_partners()
        self.assertIn("Calle Inventada 99", partner.geo_localize_error)
        self.assertIn("Sevilla", partner.geo_localize_error)
        self.assertIn("código postal", partner.geo_localize_error)
        self.assertNotIn("ciudad", partner.geo_localize_error)

    def test_service_error_is_explained(self):
        partner = self._create_partner()

        def service_down(*args):
            raise UserError("Error with geolocation server: timeout")

        with self._patch_geo_localize(service_down):
            self.Partner._cron_geo_localize_partners()
        self.assertIn("no disponible", partner.geo_localize_error)
        self.assertIn("timeout", partner.geo_localize_error)

    def test_retry_selected_partners(self):
        admin = new_test_user(
            self.env,
            login="customer_map_geo_retry_admin",
            groups="base.group_user,base.group_system",
        )
        failed = self._create_partner(name="Con error")
        failed.write(
            {
                "geo_localize_state": "failed",
                "geo_localize_attempts": 4,
                "geo_localize_error": "No se encontró la dirección",
                "geo_localize_last_try": fields.Datetime.now(),
            }
        )
        done = self._create_partner(
            name="Ya geolocalizado", partner_latitude=37.3, partner_longitude=-5.9
        )
        (failed | done).with_user(admin).action_geo_localize_retry()
        self.assertEqual(failed.geo_localize_state, "pending")
        self.assertFalse(failed.geo_localize_error)
        self.assertIn(failed, self.Partner._get_geo_localize_due_partners())
        self.assertEqual(done.geo_localize_state, "done")

        action = self.Partner.with_user(admin).action_view_geo_localize_partners(
            "failed"
        )
        self.assertIn(("geo_localize_state", "=", "failed"), action["domain"])
        self.assertNotIn(failed, self.Partner.search(action["domain"]))
        self.assertEqual(
            action["views"][0][0],
            self.env.ref("rms_customer_equipment_map.res_partner_view_list_geo_localize").id,
        )

    def test_summary_counts_states_and_next_run(self):
        admin = new_test_user(
            self.env,
            login="customer_map_geo_summary_admin",
            groups="base.group_user,base.group_system",
        )
        before = self.Partner.with_user(admin).get_geo_localize_summary()
        self._create_partner(name="Pendiente")
        self.Partner.create({"name": "Sin dirección"})
        after = self.Partner.with_user(admin).get_geo_localize_summary()
        self.assertEqual(after["pending"], before["pending"] + 1)
        self.assertEqual(after["no_address"], before["no_address"] + 1)
        self.assertTrue(after["next_run"])

    def test_summary_requires_admin(self):
        user = new_test_user(
            self.env, login="customer_map_geo_summary_user", groups="base.group_user"
        )
        with self.assertRaises(UserError):
            self.Partner.with_user(user).get_geo_localize_summary()

    def _admin(self, login):
        return new_test_user(
            self.env, login=login, groups="base.group_user,base.group_system"
        )

    def test_manual_batch_geolocates_and_reports_progress(self):
        admin = self._admin("customer_map_geo_batch_admin")
        found = self._create_partner(name="Encontrado", zip="41001")
        not_found = self._create_partner(name="No encontrado")
        self.Partner.with_user(admin).action_enqueue_geo_localize()

        def fake_geo_localize(self, street, zip_code, *args):
            return (37.38, -5.98) if zip_code else None

        with self._patch_geo_localize(fake_geo_localize):
            result = self.Partner.with_user(admin).action_geo_localize_batch(limit=50)
        self.assertEqual(result["remaining"], 0)
        self.assertFalse(result["service_error"])
        self.assertGreaterEqual(result["located"], 1)
        self.assertGreaterEqual(result["failed"], 1)
        self.assertEqual(found.geo_localize_state, "done")
        self.assertEqual(not_found.geo_localize_state, "failed")

    def test_manual_batch_reports_service_error(self):
        admin = self._admin("customer_map_geo_batch_error_admin")
        partner = self._create_partner()

        def service_down(*args):
            raise UserError("Error with geolocation server: timeout")

        with self._patch_geo_localize(service_down):
            result = self.Partner.with_user(admin).action_geo_localize_batch()
        self.assertIn("timeout", result["service_error"])
        self.assertEqual(partner.geo_localize_state, "pending")
        self.assertGreaterEqual(result["remaining"], 1)

    def test_manual_batch_requires_admin(self):
        user = new_test_user(
            self.env, login="customer_map_geo_batch_user", groups="base.group_user"
        )
        with self.assertRaises(UserError):
            self.Partner.with_user(user).action_geo_localize_batch()


class TestNominatim(TransactionCase):
    def setUp(self):
        super().setUp()
        self.patch(nominatim.time, "sleep", lambda seconds: None)

    def test_clean_street(self):
        cases = {
            "C/ Gran Vía, 28, 2º B": "Calle Gran Vía 28",
            "Polígono Ind. Calonge, nave 7B": "Polígono Industrial Calonge",
            "Avda. de la Constitución 12 bajo": "Avenida de la Constitución 12",
            "Plaza España, s/n": "Plaza España",
            "Calle Mayor nº 5, 3ºA": "Calle Mayor 5",
            "Pº de la Castellana 100": "Paseo de la Castellana 100",
            "Calle Sierpes 1": "Calle Sierpes 1",
        }
        for street, expected in cases.items():
            self.assertEqual(nominatim.clean_street(street), expected, street)

    def _response(self, status=200, payload=None, headers=None):
        response = MagicMock(status_code=status, headers=headers or {})
        if isinstance(payload, Exception):
            response.json.side_effect = payload
        else:
            response.json.return_value = payload
        return response

    def _patch_get(self, responses):
        return patch("requests.get", side_effect=responses)

    def test_rejects_result_in_another_town(self):
        majadahonda = {
            "lat": "40.47", "lon": "-3.87",
            "address": {"town": "Majadahonda", "postcode": "28220"},
        }
        madrid = {
            "lat": "40.42", "lon": "-3.70",
            "address": {"city": "Madrid", "postcode": "28013"},
        }
        with self._patch_get(
            [self._response(payload=[majadahonda]), self._response(payload=[madrid])]
        ) as get:
            result = nominatim.geo_localize(
                "C/ Gran Vía, 28", "28013", "Madrid", "Madrid", country_code="ES"
            )
        self.assertEqual(result, (40.42, -3.70))
        self.assertEqual(get.call_args_list[1].kwargs["params"]["q"], "Gran Vía 28, 28013 Madrid, Madrid")

    def test_falls_back_to_postal_code_and_returns_none_when_nothing(self):
        with self._patch_get([self._response(payload=[])] * 3):
            self.assertIsNone(
                nominatim.geo_localize("Plaza Inventada 1", "41004", "Sevilla", "Sevilla")
            )

    def test_too_many_requests_is_a_service_error_with_delay(self):
        html = ValueError("Expecting value: line 2 column 1 (char 1)")
        with self._patch_get([self._response(429, html, {"Retry-After": "12"})]):
            with self.assertRaises(nominatim.GeoLocalizeServiceError) as error:
                nominatim.geo_localize("Calle Sierpes 1", "41004", "Sevilla")
        self.assertEqual(error.exception.retry_after, 12)
        self.assertIn("429", str(error.exception))

    def test_blocked_and_invalid_answers_are_explained(self):
        with self._patch_get([self._response(403)]):
            with self.assertRaisesRegex(nominatim.GeoLocalizeServiceError, "403"):
                nominatim.geo_localize("Calle Sierpes 1", "41004", "Sevilla")
        with self._patch_get([self._response(200, ValueError("bad json"))]):
            with self.assertRaisesRegex(nominatim.GeoLocalizeServiceError, "no válida"):
                nominatim.geo_localize("Calle Sierpes 1", "41004", "Sevilla")

    def test_partner_uses_tuned_search_with_openstreetmap(self):
        partner = self.env["res.partner"].create(
            {
                "name": "Cliente Sevilla",
                "street": "C/ Sierpes, 1",
                "zip": "41004",
                "city": "Sevilla",
                "country_id": self.env.ref("base.es").id,
            }
        )
        found = {
            "lat": "37.39", "lon": "-5.99",
            "address": {"city": "Sevilla", "postcode": "41004"},
        }
        with self._patch_get([self._response(payload=[found])]) as get:
            self.assertTrue(partner._geo_localize_partner())
        params = get.call_args.kwargs["params"]
        self.assertEqual(params["q"], "Calle Sierpes 1, 41004 Sevilla")
        self.assertEqual(params["countrycodes"], "es")
        self.assertIn("User-Agent", get.call_args.kwargs["headers"])
        self.assertEqual(partner.geo_localize_state, "done")
