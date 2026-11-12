from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestSaleOrderLineWrite(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        partner = cls.env['res.partner'].create({'name': 'Cliente triple descuento'})
        product = cls.env['product.product'].create({'name': 'Producto triple descuento', 'list_price': 100})
        order = cls.env['sale.order'].create({'partner_id': partner.id})
        cls.line = cls.env['sale.order.line'].create({
            'order_id': order.id, 'product_id': product.id, 'discount1': 30,
        })

    def _discounts(self):
        return (self.line.discount1, self.line.discount2, self.line.discount3)

    def test_write_with_matching_total_keeps_breakdown(self):
        # El formulario manda el desglose junto con el total recalculado.
        self.line.write({'discount2': 10, 'discount': 37})
        self.assertEqual(self._discounts(), (30, 10, 0))
        self.assertAlmostEqual(self.line.discount, 37)
        self.assertAlmostEqual(self.line.price_subtotal, 63)

    def test_assign_matching_total_keeps_breakdown(self):
        self.line.discount2 = 10
        self.line.discount = self.line._get_final_discount()
        self.assertEqual(self._discounts(), (30, 10, 0))

    def test_different_total_still_goes_to_discount1(self):
        self.line.write({'discount2': 10})
        self.line.write({'discount': 50})
        self.assertEqual(self._discounts(), (50, 0, 0))
        self.line.write({'discount': 0})
        self.assertEqual(self._discounts(), (0, 0, 0))
