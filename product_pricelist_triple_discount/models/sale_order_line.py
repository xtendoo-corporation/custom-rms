from odoo import models, api
class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'
    def _get_display_price_ignore_combo(self):
        pricelist_item = self.pricelist_item_id
        if not pricelist_item and self.order_id.pricelist_id:
            pricelist_item_id = self.order_id.pricelist_id._get_product_rule(
                product=self.product_id,
                **self._get_pricelist_kwargs()
            )
            if pricelist_item_id:
                pricelist_item = self.env['product.pricelist.item'].browse(pricelist_item_id)
                # Necesitamos setearlo en sí mismo para que los cálculos nativos no fallen si lo usan
                self.pricelist_item_id = pricelist_item
        if pricelist_item and hasattr(pricelist_item, 'discount_active') and pricelist_item.discount_active:
            # Forzamos que se devuelva el precio ANTES de descuentos para que Odoo lo ponga en price_unit
            return self._get_pricelist_price_before_discount()
        return super()._get_display_price_ignore_combo()
    @api.depends('discount', 'product_id', 'product_uom_id', 'product_uom_qty')
    def _compute_discounts(self):
        """
        Reemplazamos el comportamiento de OCA para gestionar correctamente la lista de precios 
        sin entrar en bucles de 'squashing' o borrados de caché.
        """
        for line in self:
            pricelist_item = line.pricelist_item_id
            if not pricelist_item and line.order_id.pricelist_id and line.product_id:
                pricelist_item_id = line.order_id.pricelist_id._get_product_rule(
                    product=line.product_id,
                    **line._get_pricelist_kwargs()
                )
                if pricelist_item_id:
                    pricelist_item = self.env['product.pricelist.item'].browse(pricelist_item_id)
            
            has_pricelist_discount = pricelist_item and hasattr(pricelist_item, 'discount_active') and pricelist_item.discount_active
            
            pricelist_final_discount = 0.0
            if has_pricelist_discount:
                combined = 1.0
                for d in [pricelist_item.discount1, getattr(pricelist_item, 'discount2', 0.0), getattr(pricelist_item, 'discount3', 0.0)]:
                    if d > 0:
                        combined *= (1.0 - d / 100.0)
                pricelist_final_discount = round((1.0 - combined) * 100.0, 6)

            final_discount = line._get_final_discount() if hasattr(line, '_get_final_discount') else 0.0
            current_discount = line.discount or 0.0

            # 1. Si el descuento general difiere del calculado por el desglose Y de la tarifa,
            #    significa que el usuario o un proceso externo ha introducido un descuento total a mano.
            #    Hacemos "squash" a ese descuento manual.
            if abs(current_discount - final_discount) > 0.001 and abs(current_discount - pricelist_final_discount) > 0.001:
                line.discount1 = current_discount
                line.discount2 = 0.0
                line.discount3 = 0.0
            
            # 2. Si están a 0 (porque la línea es nueva, la caché se vació, o el usuario los borró)
            #    y tenemos una tarifa con triple descuento, la aplicamos.
            elif line.discount1 == 0.0 and line.discount2 == 0.0 and line.discount3 == 0.0:
                if has_pricelist_discount:
                    line.discount1 = pricelist_item.discount1
                    line.discount2 = getattr(pricelist_item, 'discount2', 0.0)
                    line.discount3 = getattr(pricelist_item, 'discount3', 0.0)
                else:
                    # Si no hay tarifa, respetamos que estén a 0
                    pass
            # 3. Si no son 0 y no hubo edición manual global, respetamos lo que el usuario haya escrito en discount1, 2, 3.
