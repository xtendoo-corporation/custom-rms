import logging
import time
from collections import defaultdict
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

GEO_LOCALIZE_ADDRESS_FIELDS = ("street", "zip", "city", "state_id", "country_id")
GEO_LOCALIZE_CRON_XMLID = "rms_customer_equipment_map.ir_cron_geo_localize_partners"
# Days to wait before retrying after the 1st, 2nd and 3rd failed attempt.
GEO_LOCALIZE_RETRY_DAYS = (1, 7, 30)
# Contacts processed per cron run; the cron reschedules itself until done.
GEO_LOCALIZE_CRON_BATCH = 200
# Seconds between requests: Nominatim allows at most one request per second.
GEO_LOCALIZE_REQUEST_DELAY = 1.1
GEO_LOCALIZE_MAX_SERVICE_ERRORS = 3
GEO_LOCALIZE_TRIGGER_DELAY_MINUTES = 1


class ResPartner(models.Model):
    _inherit = "res.partner"

    equipment_count = fields.Integer(
        string="Equipos",
        compute="_compute_equipment_count",
    )
    geo_localize_state = fields.Selection(
        selection=[
            ("pending", "Pendiente"),
            ("done", "Geolocalizado"),
            ("failed", "Error"),
            ("no_address", "Sin dirección"),
        ],
        string="Estado de geolocalización",
        compute="_compute_geo_localize_state",
        store=True,
        readonly=False,
        index=True,
    )
    geo_localize_attempts = fields.Integer(
        string="Intentos de geolocalización",
        compute="_compute_geo_localize_state",
        store=True,
        readonly=False,
    )
    geo_localize_error = fields.Char(
        string="Error de geolocalización",
        compute="_compute_geo_localize_state",
        store=True,
        readonly=False,
    )
    geo_localize_last_try = fields.Datetime(
        string="Último intento de geolocalización",
        readonly=True,
    )

    def _compute_equipment_count(self):
        counts_by_partner = {
            partner.id: count
            for partner, count in self.env["maintenance.equipment"]._read_group(
                domain=[("partner_id", "in", self.ids)],
                groupby=["partner_id"],
                aggregates=["__count"],
            )
        }
        for partner in self:
            partner.equipment_count = counts_by_partner.get(partner.id, 0)

    def action_view_customer_equipment(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "maintenance.hr_equipment_action"
        )
        action.update(
            {
                "name": _("Equipos de %s", self.display_name),
                "domain": [("partner_id", "=", self.id)],
                "context": {
                    **self.env.context,
                    "default_partner_id": self.id,
                },
                "view_mode": "list,form",
                "views": [(False, "list"), (False, "form")],
            }
        )
        return action

    @api.model
    def _is_customer_equipment_map_admin(self):
        return self.env.user.has_group("base.group_system")

    @api.model
    def _customer_equipment_map_partner_model(self):
        if self._is_customer_equipment_map_admin():
            return self.sudo()
        return self

    @api.model
    def get_geo_localize_summary(self):
        """Counts per geolocation state and next automatic run, for the map."""
        if not self._is_customer_equipment_map_admin():
            raise UserError(_("Only administrators can perform bulk geolocation."))
        Partner = self._customer_equipment_map_partner_model()
        counts = dict.fromkeys(("done", "pending", "failed", "no_address"), 0)
        for state, count in Partner._read_group(
            [("active", "=", True)], ["geo_localize_state"], ["__count"]
        ):
            if state in counts:
                counts[state] = count
        next_run = False
        cron = self.env.ref(GEO_LOCALIZE_CRON_XMLID, raise_if_not_found=False)
        if cron and cron.sudo().active:
            cron = cron.sudo()
            trigger = self.env["ir.cron.trigger"].sudo().search(
                [("cron_id", "=", cron.id)], order="call_at", limit=1
            )
            next_run = min(filter(None, (cron.nextcall, trigger.call_at)))
        return {**counts, "next_run": next_run}

    @api.model
    def action_view_geo_localize_partners(self, state):
        """Open the geolocation list filtered on one state."""
        if not self._is_customer_equipment_map_admin():
            raise UserError(_("Only administrators can perform bulk geolocation."))
        titles = {
            "done": _("Clientes geolocalizados"),
            "pending": _("Clientes pendientes de geolocalizar"),
            "failed": _("Clientes con error de geolocalización"),
            "no_address": _("Clientes sin dirección"),
        }
        if state not in titles:
            raise UserError(_("Estado de geolocalización desconocido: %s", state))
        return {
            "type": "ir.actions.act_window",
            "name": titles[state],
            "display_name": titles[state],
            "res_model": "res.partner",
            "domain": [("active", "=", True), ("geo_localize_state", "=", state)],
            "context": {"create": False},
            "views": [
                (
                    self.env.ref(
                        "rms_customer_equipment_map.res_partner_view_list_geo_localize"
                    ).id,
                    "list",
                ),
                (False, "form"),
            ],
            "target": "current",
        }

    def action_geo_localize_retry(self):
        """Put the selected contacts back in the geolocation queue now."""
        if not self._is_customer_equipment_map_admin():
            raise UserError(_("Only administrators can perform bulk geolocation."))
        partners = self._customer_equipment_map_partner_model().browse(self.ids)
        partners = partners.filtered(
            lambda partner: partner.geo_localize_state in ("pending", "failed")
        )
        partners.with_context(skip_geo_localize_trigger=True).write(
            {"geo_localize_state": "pending", "geo_localize_error": False}
        )
        if partners:
            cron = self.env.ref(GEO_LOCALIZE_CRON_XMLID, raise_if_not_found=False)
            if cron:
                cron.sudo()._trigger()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "message": _(
                    "%s contactos encolados: se geolocalizarán en los próximos minutos.",
                    len(partners),
                ),
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    @api.model
    def action_enqueue_geo_localize(self):
        """Queue every pending or failed contact and wake up the geolocation cron.

        Failed contacts are retried right away instead of waiting for their
        back-off delay, because an administrator explicitly asked for it.
        """
        if not self._is_customer_equipment_map_admin():
            raise UserError(_("Only administrators can perform bulk geolocation."))
        Partner = self._customer_equipment_map_partner_model()
        failed = Partner.search([("geo_localize_state", "=", "failed")])
        failed.with_context(skip_geo_localize_trigger=True).write(
            {"geo_localize_state": "pending"}
        )
        count = Partner.search_count([("geo_localize_state", "=", "pending")])
        if count:
            cron = self.env.ref(GEO_LOCALIZE_CRON_XMLID, raise_if_not_found=False)
            if cron:
                cron.sudo()._trigger()
        return {"count": count}

    # ------------------------------------------------------------------
    # Automatic geolocation
    # ------------------------------------------------------------------

    @api.depends(
        "partner_latitude",
        "partner_longitude",
        *GEO_LOCALIZE_ADDRESS_FIELDS,
    )
    def _compute_geo_localize_state(self):
        for partner in self:
            if partner.partner_latitude and partner.partner_longitude:
                state = "done"
            elif partner._has_geo_localize_address():
                state = "pending"
            else:
                state = "no_address"
            partner.geo_localize_state = state
            partner.geo_localize_attempts = 0
            partner.geo_localize_error = False

    def _has_geo_localize_address(self):
        self.ensure_one()
        return any(self[field_name] for field_name in GEO_LOCALIZE_ADDRESS_FIELDS)

    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create(vals_list)
        partners._schedule_geo_localize_cron()
        return partners

    def write(self, vals):
        result = super().write(vals)
        if any(
            field_name in vals
            for field_name in (*GEO_LOCALIZE_ADDRESS_FIELDS, "active")
        ):
            self._schedule_geo_localize_cron()
        return result

    def _schedule_geo_localize_cron(self):
        """Wake up the geolocation cron once per transaction if needed.

        Imports can create or update thousands of contacts in one transaction,
        so the trigger is registered as a pre-commit hook and deduplicated.
        """
        if self.env.context.get("skip_geo_localize_trigger"):
            return
        if not self.filtered(
            lambda partner: partner.active
            and partner.geo_localize_state == "pending"
        ):
            return
        precommit = self.env.cr.precommit
        if precommit.data.get(GEO_LOCALIZE_CRON_XMLID):
            return
        precommit.data[GEO_LOCALIZE_CRON_XMLID] = True
        precommit.add(self._trigger_geo_localize_cron)

    @api.model
    def _trigger_geo_localize_cron(self):
        cron = self.env.ref(GEO_LOCALIZE_CRON_XMLID, raise_if_not_found=False)
        if cron:
            cron.sudo()._trigger(
                fields.Datetime.now()
                + timedelta(minutes=GEO_LOCALIZE_TRIGGER_DELAY_MINUTES)
            )

    @api.model
    def _get_geo_localize_due_partners(self):
        """Return active contacts that the cron has to geolocate now.

        Pending contacts are always due. Failed contacts are retried with an
        increasing delay (see ``GEO_LOCALIZE_RETRY_DAYS``) and are abandoned
        after the last retry until their address changes.
        """
        now = fields.Datetime.now()
        partners = self.search(
            [
                ("active", "=", True),
                "|",
                ("geo_localize_state", "=", "pending"),
                "&",
                ("geo_localize_state", "=", "failed"),
                ("geo_localize_attempts", "<=", len(GEO_LOCALIZE_RETRY_DAYS)),
            ],
            order="geo_localize_last_try asc nulls first, id",
        )
        return partners.filtered(
            lambda partner: partner.geo_localize_state == "pending"
            or not partner.geo_localize_last_try
            or partner.geo_localize_last_try
            + timedelta(
                days=GEO_LOCALIZE_RETRY_DAYS[partner.geo_localize_attempts - 1]
            )
            <= now
        )

    def _geo_localize_partner(self):
        """Geolocate a single contact and store the outcome.

        :return: ``True`` if the contact was located, ``False`` if the address
            was not found. A ``UserError`` raised by the geolocation service
            (network error, quota, misconfiguration...) is propagated after
            logging it on the contact, without consuming a retry.
        """
        self.ensure_one()
        partner = self.with_context(lang="en_US", skip_geo_localize_trigger=True)
        now = fields.Datetime.now()
        try:
            result = partner._geo_localize(
                partner.street,
                partner.zip,
                partner.city,
                partner.state_id.name,
                partner.country_id.name,
            )
        except UserError as error:
            partner.write(
                {
                    "geo_localize_last_try": now,
                        "geo_localize_error": _(
                        "Servicio de geolocalización no disponible (se reintentará): %s",
                        error,
                    ),
                }
            )
            raise
        if result:
            partner.write(
                {
                    "partner_latitude": result[0],
                    "partner_longitude": result[1],
                    "date_localization": fields.Date.context_today(partner),
                    "geo_localize_last_try": now,
                }
            )
            return True
        partner.write(
            {
                "geo_localize_state": "failed",
                "geo_localize_attempts": partner.geo_localize_attempts + 1,
                "geo_localize_last_try": now,
                "geo_localize_error": self._get_geo_localize_not_found_message(),
            }
        )
        return False

    def _get_geo_localize_not_found_message(self):
        """Explain which address was searched and which parts are missing."""
        self.ensure_one()
        searched = ", ".join(
            part
            for part in (
                self.street,
                " ".join(filter(None, (self.zip, self.city))),
                self.state_id.name,
                self.country_id.name,
            )
            if part
        )
        missing = [
            label
            for label, value in (
                (_("calle"), self.street),
                (_("código postal"), self.zip),
                (_("ciudad"), self.city),
                (_("país"), self.country_id),
            )
            if not value
        ]
        message = _("No se encontró la dirección «%s».", searched)
        if missing:
            message += " " + _("Falta: %s.", ", ".join(missing))
        else:
            message += " " + _(
                "Revisa que la calle esté bien escrita (sin piso, puerta ni local)."
            )
        return message

    @api.model
    def _refresh_geo_localize_error_messages(self):
        """Explain the errors stored by previous versions of the module."""
        partners = self.with_context(active_test=False).search(
            [
                ("geo_localize_state", "=", "failed"),
                ("geo_localize_error", "in", ("Dirección no encontrada", False)),
            ]
        )
        for partner in partners:
            partner.geo_localize_error = partner._get_geo_localize_not_found_message()

    @api.model
    def _cron_geo_localize_partners(self, limit=GEO_LOCALIZE_CRON_BATCH):
        """Geolocate pending contacts in batches.

        The cron reports the remaining contacts so that Odoo reschedules it
        immediately until the queue is empty, and commits after each contact
        so a timeout never loses the work already done.
        """
        IrCron = self.env["ir.cron"]
        partners = self._get_geo_localize_due_partners()
        batch = partners[:limit]
        IrCron._commit_progress(remaining=len(partners))
        service_errors = 0
        for index, partner in enumerate(batch):
            if index:
                time.sleep(GEO_LOCALIZE_REQUEST_DELAY)
            try:
                partner._geo_localize_partner()
                service_errors = 0
            except UserError as error:
                service_errors += 1
                _logger.warning(
                    "Geolocation service error for partner %s: %s", partner.id, error
                )
            if not IrCron._commit_progress(1):
                break
            if service_errors >= GEO_LOCALIZE_MAX_SERVICE_ERRORS:
                _logger.warning(
                    "Stopping partner geolocation after %s consecutive service errors",
                    service_errors,
                )
                # Keep the remaining contacts for the next scheduled run
                # instead of hammering an unavailable service.
                IrCron._commit_progress(remaining=0)
                break

    @api.model
    def get_customer_equipment_map_data(self):
        """Return geolocated contacts allowed in the customer map."""
        self.check_access("read")
        domain = [
            ("partner_latitude", "!=", 0.0),
            ("partner_longitude", "!=", 0.0),
        ]
        Partner = self._customer_equipment_map_partner_model()
        partners = Partner.search(domain, order="name, id")

        equipment_by_partner = defaultdict(list)
        # Search all equipment with sudo() so that any user with access to
        # the partner can view all their installed products/equipments.
        equipment = self.env["maintenance.equipment"].sudo().search(
            [("partner_id", "in", partners.ids)],
            order="name, id",
        )
        for item in equipment:
            equipment_by_partner[item.partner_id.id].append(
                {
                    "id": item.id,
                    "name": item.display_name,
                    "category": item.category_id.display_name or "",
                    "serial_no": item.serial_no or "",
                }
            )

        return {
            "partners": [
                {
                    "id": partner.id,
                    "name": partner.display_name,
                    "latitude": partner.partner_latitude,
                    "longitude": partner.partner_longitude,
                    "address": partner.contact_address or "",
                    "phone": partner.phone or "",
                    "email": partner.email or "",
                    "salesperson": {
                        "id": partner.user_id.id,
                        "name": partner.user_id.display_name,
                    }
                    if partner.user_id
                    else False,
                    "country": {
                        "id": partner.country_id.id,
                        "name": partner.country_id.display_name,
                    }
                    if partner.country_id
                    else False,
                    "industry": {
                        "id": partner.industry_id.id,
                        "name": partner.industry_id.display_name,
                    }
                    if partner.industry_id
                    else False,
                    "company_type": "company" if partner.is_company else "person",
                    "contact_type": partner.type or "contact",
                    "equipment": equipment_by_partner[partner.id],
                }
                for partner in partners
            ],
            "is_admin": self._is_customer_equipment_map_admin(),
        }
