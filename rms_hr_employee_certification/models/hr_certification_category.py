from odoo import fields, models


class HrCertificationCategory(models.Model):
    _name = 'rms.hr.certification.category'
    _description = 'Categoría de Certificación de Empleado'
    _order = 'sequence, name'

    name = fields.Char(string='Nombre', required=True, translate=True)
    sequence = fields.Integer(default=10)
    color = fields.Integer(string='Color')
    active = fields.Boolean(default=True)
    description = fields.Text(string='Descripción')

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'Ya existe una categoría de certificación con este nombre.'),
    ]
