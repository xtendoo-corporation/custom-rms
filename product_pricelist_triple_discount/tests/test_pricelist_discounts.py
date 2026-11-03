from odoo.tests import Form, tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestPricelistDiscounts(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids |= cls.env.ref('sale.group_discount_per_so_line')
        cls.env.user.group_ids |= cls.env.ref('product.group_product_pricelist')
        cls.parent_category = cls.env['product.category'].create({
            'name': 'Triple discount parent',
        })
        cls.child_category = cls.env['product.category'].create({
            'name': 'Triple discount child', 'parent_id': cls.parent_category.id,
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Triple discount product', 'list_price': 100.0,
            'categ_id': cls.child_category.id, 'taxes_id': [(5, 0, 0)],
        })
        cls.pricelist = cls.env['product.pricelist'].create({
            'name': 'Triple discount 30/10/0',
            'currency_id': cls.env.company.currency_id.id,
        })
        cls._create_rule(cls.pricelist, cls.parent_category, (30, 10, 0))
        cls.partner = cls.env['res.partner'].create({
            'name': 'Triple discount customer',
            'property_product_pricelist': cls.pricelist.id,
        })

    @classmethod
    def _create_rule(cls, pricelist, category, discounts, **extra):
        factor = 1.0
        for discount in discounts:
            factor *= 1.0 - discount / 100.0
        total = round((1.0 - factor) * 100.0, 6)
        return cls.env['product.pricelist.item'].create({
            'pricelist_id': pricelist.id,
            'applied_on': '2_product_category', 'categ_id': category.id,
            'compute_price': 'triple_discount',
            'discount1': discounts[0], 'discount2': discounts[1],
            'discount3': discounts[2],
            # create() does not run the pricelist item onchange.
            'percent_price': total, 'price_discount': total,
            **extra,
        })

    def _create_order(self, pricelist=None):
        return self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'pricelist_id': (pricelist or self.pricelist).id,
        })

    def _create_line(self, order=None, **extra):
        return self.env['sale.order.line'].create({
            'order_id': (order or self._create_order()).id,
            'product_id': self.product.id, 'product_uom_qty': 1,
            **extra,
        })

    def _assert_discounts(self, line, expected):
        self.assertEqual((line.discount1, line.discount2, line.discount3), expected)

    def _reload(self, line):
        fields = ['discount1', 'discount2', 'discount3', 'discount', 'price_subtotal']
        line.flush_recordset(fields)
        line.invalidate_recordset(fields)
        return line

    def test_form_applies_rule_before_save(self):
        order_form = Form(self.env['sale.order'])
        order_form.partner_id = self.partner
        self.assertEqual(order_form.pricelist_id, self.pricelist)
        with order_form.order_line.new() as line_form:
            line_form.product_id = self.product
            self._assert_discounts(line_form, (30, 10, 0))
            self.assertAlmostEqual(line_form.discount, 37)
        line = self._reload(order_form.save().order_line)
        self._assert_discounts(line, (30, 10, 0))
        self.assertAlmostEqual(line.discount, 37)
        self.assertAlmostEqual(line.price_unit, 100)
        self.assertAlmostEqual(line.price_subtotal, 63)

    def test_create_without_discounts_applies_rule(self):
        line = self._reload(self._create_line())
        self._assert_discounts(line, (30, 10, 0))
        self.assertAlmostEqual(line.discount, 37)
        self.assertAlmostEqual(line.price_subtotal, 63)

    def test_child_zero_rule_wins(self):
        self._create_rule(self.pricelist, self.child_category, (0, 0, 0))
        line = self._reload(self._create_line())
        self._assert_discounts(line, (0, 0, 0))
        self.assertAlmostEqual(line.discount, 0)
        self.assertAlmostEqual(line.price_subtotal, 100)

    def test_no_rule(self):
        pricelist = self.env['product.pricelist'].create({'name': 'No discount rules'})
        line = self._reload(self._create_line(order=self._create_order(pricelist)))
        self._assert_discounts(line, (0, 0, 0))
        self.assertAlmostEqual(line.discount, 0)

    def test_manual_discount_persists(self):
        line = self._create_line()
        line.write({'discount2': 5})
        self._assert_discounts(self._reload(line), (30, 5, 0))
        self.assertAlmostEqual(line.discount, 33.5)
        self.assertAlmostEqual(line.price_subtotal, 66.5)

    def test_explicit_create_preserves_breakdown(self):
        line = self._reload(self._create_line(discount1=12, discount2=3))
        self._assert_discounts(line, (12, 3, 0))
        self.assertAlmostEqual(line.discount, 14.64)
        self.assertAlmostEqual(line.price_subtotal, 85.36)

    def test_explicit_create_ignores_computed_total(self):
        # The form/import may supply the total too; OCA treats zero as a reset.
        line = self._reload(self._create_line(discount1=12, discount2=3, discount=0))
        self._assert_discounts(line, (12, 3, 0))
        self.assertAlmostEqual(line.discount, 14.64)

    def test_explicit_create_only_second_discount(self):
        line = self._reload(self._create_line(discount2=3))
        self._assert_discounts(line, (0, 3, 0))
        self.assertAlmostEqual(line.discount, 3)

    def test_quantity_change_reapplies_rule(self):
        line = self._create_line(discount1=12, discount2=3)
        line.write({'product_uom_qty': 2})
        self._assert_discounts(self._reload(line), (30, 10, 0))
        self.assertAlmostEqual(line.price_subtotal, 126)
        # A quantity-dependent winner must replace the previously cached rule.
        self._create_rule(self.pricelist, self.child_category, (20, 5, 2), min_quantity=3)
        line.write({'product_uom_qty': 3})
        self._assert_discounts(self._reload(line), (20, 5, 2))

    def test_update_prices_applies_new_pricelist(self):
        line = self._create_line()
        pricelist = self.env['product.pricelist'].create({'name': 'Triple discount 20/5/2'})
        self._create_rule(pricelist, self.parent_category, (20, 5, 2))
        line.order_id.pricelist_id = pricelist
        line.order_id.action_update_prices()
        self._assert_discounts(self._reload(line), (20, 5, 2))
        self.assertAlmostEqual(line.discount, 25.52)
        self.assertAlmostEqual(line.price_subtotal, 74.48)

    def test_update_prices_clears_discounts_without_active_rule(self):
        for zero_rule in (False, True):
            with self.subTest(zero_rule=zero_rule):
                line = self._create_line()
                self._assert_discounts(line, (30, 10, 0))
                pricelist = self.env['product.pricelist'].create({
                    'name': 'Pricelist without active discounts',
                })
                if zero_rule:
                    self._create_rule(pricelist, self.parent_category, (0, 0, 0))
                line.order_id.pricelist_id = pricelist
                line.order_id.action_update_prices()
                self._assert_discounts(self._reload(line), (0, 0, 0))
                self.assertAlmostEqual(line.discount, 0)
                self.assertAlmostEqual(line.price_subtotal, 100)
