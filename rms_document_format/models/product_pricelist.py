from odoo import fields, models


class ProductPricelist(models.Model):
    _inherit = 'product.pricelist'

    rms_hide_price_detail = fields.Boolean(
        string="Ocultar descuentos en presupuesto",
        help="Si está marcado, el PDF del presupuesto no mostrará el PVP "
             "original ni el desglose de descuentos (Dto1/Dto2/Dto3) de las "
             "líneas: solo el producto, el precio unitario y el total, ya "
             "con el descuento aplicado.",
    )
