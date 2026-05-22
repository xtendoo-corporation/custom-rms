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

    def _inverse_discount(self):
        """
        Interceptamos la inversión del descuento general de OCA. Si proviene del cálculo nativo de la 
        tarifa con triple descuento, mantenemos el desglose original en lugar de aplastarlo todo en discount1.
        """
        for rec in self:
            pricelist_item = rec.pricelist_item_id
            if not pricelist_item and rec.order_id.pricelist_id and rec.product_id:
                pricelist_item_id = rec.order_id.pricelist_id._get_product_rule(
                    product=rec.product_id,
                    **rec._get_pricelist_kwargs()
                )
                if pricelist_item_id:
                    pricelist_item = self.env['product.pricelist.item'].browse(pricelist_item_id)
            
            has_pricelist_discount = pricelist_item and hasattr(pricelist_item, 'discount_active') and pricelist_item.discount_active
            
            if has_pricelist_discount:
                combined = 1.0
                for d in [pricelist_item.discount1, getattr(pricelist_item, 'discount2', 0.0), getattr(pricelist_item, 'discount3', 0.0)]:
                    if d > 0:
                        combined *= (1.0 - d / 100.0)
                pricelist_final_discount = round((1.0 - combined) * 100.0, 6)
                
                # Si el descuento general coincide con el calculado por la tarifa o es un reseteo (0.0),
                # aplicamos y mantenemos el desglose
                if abs((rec.discount or 0.0) - pricelist_final_discount) < 0.001 or (rec.discount or 0.0) == 0.0:
                    rec.update({
                        "discount1": pricelist_item.discount1,
                        "discount2": getattr(pricelist_item, 'discount2', 0.0),
                        "discount3": getattr(pricelist_item, 'discount3', 0.0)
                    })
                    # Sincronizamos explícitamente rec.discount para que el onchange devuelva el subtotal correcto a la vista
                    rec.discount = rec._get_final_discount() if hasattr(rec, '_get_final_discount') else 0.0
                    continue
            
            super()._inverse_discount()

    @api.depends('product_id', 'product_uom_id', 'product_uom_qty')
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
            
            # Si forzamos la lista de precios (por ejemplo, al actualizar tarifas), aplicamos directamente el desglose
            if self.env.context.get('force_pricelist_discounts'):
                if has_pricelist_discount:
                    line.discount1 = pricelist_item.discount1
                    line.discount2 = getattr(pricelist_item, 'discount2', 0.0)
                    line.discount3 = getattr(pricelist_item, 'discount3', 0.0)
                else:
                    line.discount1 = 0.0
                    line.discount2 = 0.0
                    line.discount3 = 0.0
                line.discount = line._get_final_discount() if hasattr(line, '_get_final_discount') else 0.0
                continue

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
                    line.discount1 = 0.0
                    line.discount2 = 0.0
                    line.discount3 = 0.0
            # 3. Si no son 0 y no hubo edición manual global, respetamos lo que el usuario haya escrito en discount1, 2, 3.
            else:
                line.discount1 = line.discount1
                line.discount2 = line.discount2
                line.discount3 = line.discount3

            # Sincronizamos explícitamente line.discount para asegurar que el subtotal se calcule correctamente
            line.discount = line._get_final_discount() if hasattr(line, '_get_final_discount') else 0.0


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _recompute_prices(self):
        super()._recompute_prices()
        lines_to_recompute = self._get_update_prices_lines()
        # Forzamos el cálculo de los descuentos triples basados en la nueva lista de precios pasándole el contexto
        lines_to_recompute.with_context(force_pricelist_discounts=True)._compute_discounts()
        # Forzamos que se vuelva a calcular el descuento general (discount) combinando los nuevos discount1, 2, 3
        lines_to_recompute._compute_discount()
