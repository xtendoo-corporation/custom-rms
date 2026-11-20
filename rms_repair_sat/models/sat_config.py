from odoo import fields, models
from .repair_order import SAT_STAGES


class RepairStageLimit(models.Model):
    _name = 'rms.repair.stage.limit'
    _description = 'Días por fase SAT'
    _order = 'id'

    stage = fields.Selection(SAT_STAGES, string='Fase', required=True)
    days = fields.Integer(string='Días', required=True, default=7)
    _stage_unique = models.Constraint('UNIQUE(stage)', 'La fase ya tiene un límite.')
    _days_positive = models.Constraint('CHECK(days >= 0)', 'Los días no pueden ser negativos.')


class RepairAccessory(models.Model):
    _name = 'rms.repair.accessory'
    _description = 'Accesorio SAT'
    _order = 'sequence, id'

    name = fields.Char(string='Nombre', required=True)
    active = fields.Boolean(string='Activo', default=True)
    sequence = fields.Integer(string='Orden', default=10)


class ProductCategory(models.Model):
    _inherit = 'product.category'

    rms_warranty_months = fields.Integer(string='Garantía de la marca (meses)')
    _rms_warranty_positive = models.Constraint('CHECK(rms_warranty_months >= 0)', 'Los meses no pueden ser negativos.')
