from odoo import models, fields, api
class ProductPricelistItem(models.Model):
    _inherit = 'product.pricelist.item'
    discount1 = fields.Float(
        string='Descuento 1 (%)',
        digits=(6, 2),
        default=0.0,
        help='Primer descuento aplicado al precio base.',
    )
    discount2 = fields.Float(
        string='Descuento 2 (%)',
        digits=(6, 2),
        default=0.0,
        help='Segundo descuento aplicado sobre el precio resultante del primer descuento.',
    )
    discount3 = fields.Float(
        string='Descuento 3 (%)',
        digits=(6, 2),
        default=0.0,
        help='Tercer descuento aplicado sobre el precio resultante de los dos descuentos anteriores.',
    )
    discount_active = fields.Boolean(
        string='Descuentos activos',
        compute='_compute_discount_active',
        store=True,
        help='Se activa automáticamente cuando al menos uno de los tres descuentos es mayor que 0.',
    )
    @api.depends('discount1', 'discount2', 'discount3')
    def _compute_discount_active(self):
        for record in self:
            record.discount_active = any([
                record.discount1 > 0,
                record.discount2 > 0,
                record.discount3 > 0,
            ])
    @api.onchange('discount1', 'discount2', 'discount3')
    def _onchange_triple_discount(self):
        """
        Al introducir cualquier descuento:
        - Activa compute_price en 'percentage'
        - Calcula el descuento combinado en cascada y lo asigna a price_discount
        """
        if self.discount1 > 0 or self.discount2 > 0 or self.discount3 > 0:
            self.compute_price = 'percentage'
            combined = 1.0
            for d in [self.discount1, self.discount2, self.discount3]:
                if d > 0:
                    combined *= (1.0 - d / 100.0)
            self.price_discount = round((1.0 - combined) * 100.0, 6)
