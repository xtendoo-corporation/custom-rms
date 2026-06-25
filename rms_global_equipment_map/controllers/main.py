from odoo import http
from odoo.http import request


class GlobalEquipmentMapController(http.Controller):
    @http.route(
        "/rms_global_equipment_map/partners",
        type="json",
        auth="user",
        methods=["POST"],
    )
    def get_global_equipment_map_partners(self):
        Partner = request.env["res.partner"].sudo()
        fields_to_read = [
            "id",
            "name",
            "partner_latitude",
            "partner_longitude",
            "equipment_model_tag_ids",
        ]
        partners = Partner.search_read(
            [
                ("partner_latitude", "!=", 0.0),
                ("partner_longitude", "!=", 0.0),
            ],
            fields_to_read,
            order="name, id",
        )

        model_ids = set()
        for partner in partners:
            model_ids.update(partner.get("equipment_model_tag_ids") or [])

        equipment_models = {
            model.id: model.display_name
            for model in request.env["equipment.model.tag"].sudo().browse(model_ids).exists()
        }

        return [
            {
                "id": partner["id"],
                "name": partner.get("name") or "",
                "latitude": partner["partner_latitude"],
                "longitude": partner["partner_longitude"],
                "equipment_models": [
                    {"id": model_id, "name": equipment_models[model_id]}
                    for model_id in partner.get("equipment_model_tag_ids", [])
                    if model_id in equipment_models
                ],
            }
            for partner in partners
        ]
