from odoo import fields, models


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    rms_requested_state_id = fields.Many2one(
        'product.state', string='Estado pedido (el que sea)',
        domain="[('code', 'in', ('new', 'ex_demo', 'second_hand'))]",
        help="Para vender «el que sea» de un estado (Ex-Demo o 2ª mano) sin fijar "
             "el nº de serie: en el checklist de salida vale cualquier equipo de "
             "ese estado. Vacío = Nuevo. Si la línea tiene nº de serie elegidos, "
             "mandan los nº de serie.",
    )
