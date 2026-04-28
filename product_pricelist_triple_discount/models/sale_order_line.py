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
    @api.depends('product_id', 'product_uom_id', 'product_uom_qty')
    def _compute_discount(self):
        res = super()._compute_discount()
        for line in self:
            if not line.product_id or line.display_type or not line.order_id.pricelist_id:
                continue
            pricelist_item = line.pricelist_item_id
            if not pricelist_item:
                pricelist_item_id = line.order_id.pricelist_id._get_product_rule(
                    product=line.product_id,
                    **line._get_pricelist_kwargs()
                )
                if pricelist_item_id:
                    pricelist_item = self.env['product.pricelist.item'].browse(pricelist_item_id)
            if pricelist_item and hasattr(pricelist_item, 'discount_active') and pricelist_item.discount_active:
                if hasattr(line, 'discount1'):
                    line.discount1 = pricelist_item.discount1
                    line.discount2 = pricelist_item.discount2
                    line.discount3 = pricelist_item.discount3
                    if hasattr(line, '_get_final_discount'):
                        line.discount = line._get_final_discount()
        return res
