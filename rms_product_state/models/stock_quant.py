from odoo import models, fields


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    product_state_id = fields.Many2one(
        related='lot_id.product_state_id',
        string='Estado',
        store=True,
        readonly=False,
        help="Estado del número de serie/lote. Editable desde aquí: se "
             "actualiza directamente en el número de serie."
    )
