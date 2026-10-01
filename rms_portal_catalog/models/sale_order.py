from odoo import fields, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    rms_portal_cart = fields.Boolean(
        string='Presupuesto del portal',
        help='Presupuesto que el propio cliente va montando desde el '
             'catálogo B2B del portal (botón "Añadir al presupuesto" en '
             '"Ver precios"), en vez de una cotización creada por un '
             'comercial.',
    )
