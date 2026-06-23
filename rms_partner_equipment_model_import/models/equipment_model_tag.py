from odoo import api, fields, models


def normalize_name(value):
    """Normalize names for deterministic, case-insensitive matching."""
    return " ".join(str(value or "").split()).casefold()


class EquipmentModelTag(models.Model):
    _name = "equipment.model.tag"
    _description = "Modelo de equipo"
    _order = "name"

    name = fields.Char(string="Nombre", required=True, index=True)
    normalized_name = fields.Char(
        string="Nombre normalizado",
        required=True,
        index=True,
        copy=False,
    )
    active = fields.Boolean(default=True)
    partner_ids = fields.Many2many(
        comodel_name="res.partner",
        relation="res_partner_equipment_model_tag_rel",
        column1="equipment_model_tag_id",
        column2="partner_id",
        string="Compañías",
        readonly=True,
    )
    partner_count = fields.Integer(
        string="Compañías",
        compute="_compute_partner_count",
    )

    _normalized_name_unique = models.Constraint(
        "UNIQUE(normalized_name)",
        "Ya existe un modelo de equipo con ese nombre.",
    )

    @api.depends("partner_ids")
    def _compute_partner_count(self):
        for record in self:
            record.partner_count = len(record.partner_ids)

    @api.model_create_multi
    def create(self, vals_list):
        prepared_vals_list = []
        for vals in vals_list:
            vals = dict(vals)
            vals["name"] = " ".join(str(vals.get("name") or "").split())
            vals["normalized_name"] = normalize_name(vals["name"])
            prepared_vals_list.append(vals)
        return super().create(prepared_vals_list)

    def write(self, vals):
        vals = dict(vals)
        if "name" in vals:
            vals["name"] = " ".join(str(vals["name"] or "").split())
            vals["normalized_name"] = normalize_name(vals["name"])
        return super().write(vals)
