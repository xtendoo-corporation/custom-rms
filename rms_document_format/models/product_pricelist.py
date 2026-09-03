from odoo import fields, models


class ProductPricelist(models.Model):
    _inherit = 'product.pricelist'

    rms_hide_price_detail = fields.Boolean(
        string="Ocultar precio unitario y descuentos en presupuesto",
        help="Si está marcado, el PDF del presupuesto no mostrará el precio "
             "unitario ni los descuentos (Dto1/Dto2/Dto3) de las líneas: solo "
             "el producto y el precio neto final.",
    )
