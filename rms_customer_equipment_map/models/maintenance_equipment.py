from odoo import fields, models


class MaintenanceEquipment(models.Model):
    _inherit = "maintenance.equipment"

    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Cliente / Ubicación",
        check_company=True,
        index="btree_not_null",
        tracking=True,
    )
