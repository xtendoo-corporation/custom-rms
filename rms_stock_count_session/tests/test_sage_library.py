# -*- coding: utf-8 -*-
import base64
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged, new_test_user


@tagged('post_install', '-at_install')
class TestSageLibrary(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.brand = cls.env['product.category'].create({'name': 'Test Library'})
        cls.product = cls.env['product.product'].create({'name': 'Library Model', 'default_code': 'LIB-MODEL'})
        cls.manager = new_test_user(cls.env, login='sage_library_manager', groups='stock.group_stock_manager')
        cls.operator = new_test_user(cls.env, login='sage_library_operator', groups='stock.group_stock_user')
        sales_group = cls.env.ref('sales_team.group_sale_salesman', raise_if_not_found=False)
        cls.sales = new_test_user(
            cls.env, login='sage_library_sales',
            groups='sales_team.group_sale_salesman' if sales_group else 'base.group_user',
        )

    def _upload(self, serial='777', mode='add', warehouse='AL1', article='LIB-MODEL', price=True, duplicate=False):
        header = 'Almacén;Artículo;Lotes;Unidades' + (';Precio' if price else '')
        detail = '%s;%s;%s;1' % (warehouse, article, serial) + (';12,50' if price else '')
        raw = (header + '\n' + detail).encode('latin-1')
        wizard = self.env['rms.stock.count.sage.import'].with_user(self.manager).create({
            'brand_categ_id': self.brand.id, 'file_data': base64.b64encode(raw),
            'filename': 'export.csv', 'mode': mode, 'allow_duplicate': duplicate,
        })
        action = wizard.action_import()
        return self.env['rms.sage.snapshot'].browse(action['res_id'])

    def test_append_and_replace_version(self):
        first = self._upload()
        second = self._upload('778')
        self.assertEqual((first | second).mapped('state'), ['current', 'current'])
        third = self._upload('779', mode='replace')
        self.assertEqual(set((first | second).mapped('state')), {'replaced'})
        self.assertFalse(any((first | second).line_ids.mapped('is_current')))
        self.assertTrue(third.line_ids.is_current)
        self.assertEqual(third.line_ids.product_id, self.product)
        self.assertEqual(third.line_ids.sudo().cost, 12.5)

    def test_duplicate_serial_different_warehouse_and_state(self):
        first = self._upload(article='D-LIB-MODEL')
        second = self._upload(warehouse='A.2')
        self.assertEqual((first | second).line_ids.mapped('dup_count'), [2, 2])
        self.assertEqual(set((first | second).line_ids.mapped('state')), {'nuevo', 'demo'})

    def test_no_serial_quantities_are_not_duplicates(self):
        first = self._upload(serial='', article='LIB-MODEL')
        second = self._upload(serial='', article='D-LIB-MODEL', warehouse='A.2')
        self.assertEqual((first | second).line_ids.mapped('dup_count'), [0, 0])

    def test_hash_warning_and_optional_column_warning(self):
        self._upload()
        with self.assertRaises(UserError):
            self._upload()
        snapshot = self._upload('780', price=False)
        self.assertIn('Precio', snapshot.quality_warnings)
        wizard = self.env['rms.stock.count.sage.import'].create({'brand_categ_id': self.brand.id,
            'filename': 'bad.csv', 'file_data': base64.b64encode(b'Articulo;Cantidad\nX;1')})
        with self.assertRaises(UserError):
            wizard.action_import()

    def test_sales_denied_and_cost_restricted(self):
        line = self._upload().line_ids
        with self.assertRaises(AccessError):
            line.with_user(self.sales).read(['serial'])
        self.assertTrue(line.with_user(self.operator).read(['serial']))
        with self.assertRaises(AccessError):
            line.with_user(self.operator).read(['cost'])
        with self.assertRaises(AccessError):
            line.with_user(self.manager).read(['cost'])
