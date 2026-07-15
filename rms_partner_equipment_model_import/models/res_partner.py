from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    equipment_model_tag_ids = fields.Many2many(
        comodel_name="equipment.model.tag",
        relation="res_partner_equipment_model_tag_rel",
        column1="partner_id",
        column2="equipment_model_tag_id",
        string="Equipos del Cliente",
        help="Equipos del Cliente asociados a esta compañía.",
    )
