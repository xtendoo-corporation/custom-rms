from odoo import models, fields

class ProductState(models.Model):
    _name = 'product.state'
    _description = 'Estado de Producto'
    _order = 'sequence, id'

    name = fields.Char(string='Nombre', required=True, translate=True)
    code = fields.Char(string='Código', required=True)
    sequence = fields.Integer(string='Secuencia', default=10)
    active = fields.Boolean(string='Activo', default=True)

    _sql_constraints = [
        ('code_unique', 'unique(code)', 'El código del estado debe ser único.'),
    ]
