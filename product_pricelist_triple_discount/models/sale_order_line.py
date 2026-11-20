from odoo import models, fields, api
class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    discount2 = fields.Float(
        compute='_compute_discount1', store=True, readonly=False,
        precompute=True, compute_sudo=True,
    )
    discount3 = fields.Float(
        compute='_compute_discount1', store=True, readonly=False,
        precompute=True, compute_sudo=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        discount_fields = self._get_multiple_discount_field_names()
        normalized_vals = []
        for vals in vals_list:
            vals = dict(vals)
            if any(field in vals for field in discount_fields):
                # Supplying all components prevents precompute from mixing an
                # imported/manual breakdown with the pricelist rule. The total
                # is computed; OCA also treats an explicit zero as a reset.
                for field in discount_fields:
                    vals.setdefault(field, 0.0)
                vals.pop('discount', None)
            normalized_vals.append(vals)
        return super().create(normalized_vals)

    def write(self, vals):
        """
        La mixin de OCA (triple.discount.mixin.write) pasa cualquier 'discount'
        que llegue a discount1 y pone discount2 y discount3 a 0, aunque vengan
        en los mismos valores. Si el descuento total es justo el que resulta de
        discount1/2/3 no aporta nada (se recalcula a partir de ellos), así que
        lo quitamos para que no aplaste el desglose (30 % + 10 % -> 37 % + 0 %).
        Un total distinto (p. ej. el reseteo a 0 de "Actualizar precios") se
        sigue pasando a OCA como hasta ahora.
        """
        if 'discount' in vals and hasattr(self, '_get_aggregated_multiple_discounts'):
            discount_fields = self._get_multiple_discount_field_names()
            if all(
                abs(line._get_aggregated_multiple_discounts(
                    [vals.get(field, line[field]) for field in discount_fields]
                ) - (vals['discount'] or 0.0)) < 0.000001
                for line in self
            ):
                vals = dict(vals)
                vals.pop('discount')
        return super().write(vals)

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

    def _get_pricelist_discount_rule(self):
        """Look up the current winning rule, including a child zero rule."""
        self.ensure_one()
        rule = self.env['product.pricelist.item']
        if self.product_id and self.order_id.pricelist_id:
            rule_id = self.order_id.pricelist_id._get_product_rule(
                product=self.product_id, **self._get_pricelist_kwargs()
            )
            rule = rule.browse(rule_id) if rule_id else rule
        return rule

    @api.depends('product_id', 'product_uom_id', 'product_uom_qty')
    def _compute_discount1(self):
        native_lines = self.env['sale.order.line']
        for line in self:
            rule = line._get_pricelist_discount_rule()
            if rule and rule.discount_active:
                line.discount1 = rule.discount1
                line.discount2 = rule.discount2
                line.discount3 = rule.discount3
            else:
                # These are computed by the same method, so initialize them
                # before OCA reads the total while computing native discount1.
                line.discount2 = 0.0
                line.discount3 = 0.0
                native_lines |= line
        if native_lines:
            super(SaleOrderLine, native_lines)._compute_discount1()

    def _compute_discounts(self):
        """Compatibility entry point for explicit pricelist reapplication."""
        if not self.env.context.get('force_pricelist_discounts'):
            self._compute_discount1()
        else:
            for line in self:
                rule = line._get_pricelist_discount_rule()
                active = rule and rule.discount_active
                line.discount1 = rule.discount1 if active else 0.0
                line.discount2 = rule.discount2 if active else 0.0
                line.discount3 = rule.discount3 if active else 0.0
        for line in self:
            line.discount = line._get_final_discount()


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _recompute_prices(self):
        super()._recompute_prices()
        lines_to_recompute = self._get_update_prices_lines()
        # This also synchronizes the total. Calling OCA's discount compute
        # directly afterwards can write native zero and erase the breakdown.
        lines_to_recompute.with_context(force_pricelist_discounts=True)._compute_discounts()
