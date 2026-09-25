from odoo import api, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    @api.model
    def _global_equipment_map_partner_model(self):
        """Administrators see every contact; other users only what their
        record rules allow, as in the customer map."""
        if self.env.user.has_group("base.group_system"):
            return self.sudo()
        return self

    @api.model
    def get_global_equipment_map_partners(self, partner_ids=None):
        """Return the geolocated contacts shown in the global equipment map.

        :param partner_ids: optional list of ids to restrict the result to.
            Ids the current user is not allowed to read are silently ignored.
        """
        self.check_access("read")
        Partner = self._global_equipment_map_partner_model()
        domain = [
            ("partner_latitude", "!=", 0.0),
            ("partner_longitude", "!=", 0.0),
        ]
        if partner_ids is not None:
            domain.append(("id", "in", [int(partner_id) for partner_id in partner_ids]))
        partners = Partner.search(domain, order="name, id")

        # Equipment model names and child contacts are read with sudo(): the
        # user is already allowed to see the company they belong to.
        partners_sudo = partners.sudo()
        result = []
        for partner in partners_sudo:
            contact = partner.child_ids.filtered(
                lambda child: child.type == "contact" and child.name
            )[:1]
            result.append(
                {
                    "id": partner.id,
                    "name": partner.name or "",
                    "latitude": partner.partner_latitude,
                    "longitude": partner.partner_longitude,
                    "contact_name": contact.name or "",
                    "email": partner.email or contact.email or "",
                    "phone": partner.phone or contact.phone or "",
                    "equipment_models": [
                        {"id": model.id, "name": model.display_name}
                        for model in partner.equipment_model_tag_ids
                    ],
                }
            )
        return result
