import base64
import io

from odoo import http
from odoo.exceptions import UserError
from odoo.http import request

try:
    import openpyxl
    from openpyxl.styles import Font
except ImportError:
    openpyxl = None
    Font = None


class GlobalEquipmentMapController(http.Controller):
    def _read_partners(self, partner_ids=None):
        Partner = request.env["res.partner"].sudo()
        domain = [
            ("partner_latitude", "!=", 0.0),
            ("partner_longitude", "!=", 0.0),
        ]
        if partner_ids is not None:
            domain.append(("id", "in", partner_ids))
        fields_to_read = [
            "id",
            "name",
            "partner_latitude",
            "partner_longitude",
            "equipment_model_tag_ids",
        ]
        partners = Partner.search_read(domain, fields_to_read, order="name, id")

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

    @http.route(
        "/rms_global_equipment_map/partners",
        type="json",
        auth="user",
        methods=["POST"],
    )
    def get_global_equipment_map_partners(self):
        return self._read_partners()

    @http.route(
        "/rms_global_equipment_map/export_xlsx",
        type="json",
        auth="user",
        methods=["POST"],
    )
    def export_global_equipment_map_xlsx(self, partner_ids=None):
        if openpyxl is None:
            raise UserError(
                "No se puede generar el Excel: falta instalar la librería "
                "'openpyxl' en el servidor."
            )

        partners = self._read_partners(partner_ids or [])

        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = "Empresas"

        headers = [
            "Empresa",
            "Nº de Equipos",
            "Equipos del Cliente",
            "Latitud",
            "Longitud",
        ]
        sheet.append(headers)
        for cell in sheet[1]:
            cell.font = Font(bold=True)

        for partner in partners:
            model_names = ", ".join(model["name"] for model in partner["equipment_models"])
            sheet.append(
                [
                    partner["name"],
                    len(partner["equipment_models"]),
                    model_names,
                    partner["latitude"],
                    partner["longitude"],
                ]
            )

        widths = [40, 14, 60, 12, 12]
        for index, width in enumerate(widths, start=1):
            sheet.column_dimensions[sheet.cell(row=1, column=index).column_letter].width = width

        buffer = io.BytesIO()
        workbook.save(buffer)

        return {
            "filename": "mapa_global_equipos.xlsx",
            "content": base64.b64encode(buffer.getvalue()).decode("ascii"),
        }
