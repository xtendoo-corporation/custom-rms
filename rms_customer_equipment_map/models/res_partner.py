from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ResPartner(models.Model):
    _inherit = "res.partner"

    equipment_count = fields.Integer(
        string="Equipos",
        compute="_compute_equipment_count",
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
    def get_bulk_geolocation_candidates(self):
        self.check_access("read")
        partners = self.search(
            [
                ("active", "=", True),
                "|",
                ("partner_latitude", "=", 0.0),
                ("partner_longitude", "=", 0.0),
            ],
            order="name, id",
        )
        candidates = partners.filtered(
            lambda partner: any(
                (
                    partner.street,
                    partner.zip,
                    partner.city,
                    partner.state_id,
                    partner.country_id,
                )
            )
        )
        return {
            "ids": candidates.ids,
            "count": len(candidates),
            "without_address": len(partners - candidates),
        }

    @api.model
    def bulk_geo_localize_partners(self, partner_ids):
        partners = self.browse(partner_ids).exists()
        partners.check_access("write")
        localized = []
        failed = []
        for partner in partners.with_context(lang="en_US"):
            try:
                result = self._geo_localize(
                    partner.street,
                    partner.zip,
                    partner.city,
                    partner.state_id.name,
                    partner.country_id.name,
                )
                if result:
                    partner.write(
                        {
                            "partner_latitude": result[0],
                            "partner_longitude": result[1],
                            "date_localization": fields.Date.context_today(partner),
                        }
                    )
                    localized.append(partner.id)
                else:
                    failed.append(
                        {"id": partner.id, "name": partner.display_name}
                    )
            except UserError as error:
                return {
                    "localized_ids": localized,
                    "failed": failed,
                    "error": str(error),
                }
        return {"localized_ids": localized, "failed": failed, "error": False}

    @api.model
    def get_customer_equipment_map_data(self):
        """Return geolocated contacts and their installed equipment."""
        self.check_access("read")
        partners = self.search(
            [
                ("partner_latitude", "!=", 0.0),
                ("partner_longitude", "!=", 0.0),
            ],
            order="name, id",
        )

        equipment_by_partner = defaultdict(list)
        equipment = self.env["maintenance.equipment"].search(
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

        equipment_models_by_partner = defaultdict(list)
        if "equipment_model_tag_ids" in self._fields:
            equipment_models_by_partner.update(
                {
                    partner.id: [
                        {"id": model.id, "name": model.display_name}
                        for model in partner.equipment_model_tag_ids
                    ]
                    for partner in partners.sudo()
                }
            )

        return [
            {
                "id": partner.id,
                "name": partner.display_name,
                "latitude": partner.partner_latitude,
                "longitude": partner.partner_longitude,
                "address": partner.contact_address or "",
                "phone": partner.phone or "",
                "email": partner.email or "",
                "tags": [
                    {
                        "id": category.id,
                        "name": category.display_name,
                        "color": category.color,
                    }
                    for category in partner.category_id
                ],
                "equipment_models": equipment_models_by_partner[partner.id],
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
        ]
