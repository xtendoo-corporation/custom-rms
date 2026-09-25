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
        partners = Partner.search(domain, order="name, id")

        model_ids = set()
        for partner in partners:
            model_ids.update(partner.equipment_model_tag_ids.ids)

        equipment_models = {
            model.id: model.display_name
            for model in request.env["equipment.model.tag"].sudo().browse(model_ids).exists()
        }

        result = []
        for partner in partners:
            contact = partner.child_ids.filtered(lambda child: child.type == "contact" and child.name)[:1]
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
                        {"id": model.id, "name": equipment_models[model.id]}
                        for model in partner.equipment_model_tag_ids
                        if model.id in equipment_models
                    ],
                }
            )
        return result

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
            "Nombre de Contacto",
            "Correo",
            "Teléfono",
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
                    partner["contact_name"],
                    partner["email"],
                    partner["phone"],
                    len(partner["equipment_models"]),
                    model_names,
                    partner["latitude"],
                    partner["longitude"],
                ]
            )

        widths = [40, 24, 28, 18, 14, 60, 12, 12]
        for index, width in enumerate(widths, start=1):
            sheet.column_dimensions[sheet.cell(row=1, column=index).column_letter].width = width

        buffer = io.BytesIO()
        workbook.save(buffer)

        return {
            "filename": "mapa_global_equipos.xlsx",
            "content": base64.b64encode(buffer.getvalue()).decode("ascii"),
        }
