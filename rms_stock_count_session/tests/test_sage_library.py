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
        cls.product = cls.env['product.product'].create({'name': 'Library Model', 'default_code': 'LIB-MODEL', 'categ_id': cls.brand.id})
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
            'scope': 'brand', 'brand_categ_id': self.brand.id, 'file_data': base64.b64encode(raw),
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
        wizard = self.env['rms.stock.count.sage.import'].create({'scope': 'brand', 'brand_categ_id': self.brand.id,
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


@tagged('post_install', '-at_install')
class TestSageFullCompanyImport(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.brands = {}
        for name in ('Sony', 'DiGiCo', 'Auvitran', 'Absent Sage Test'):
            cls.brands[name] = cls.env['product.category'].search([
                ('name', '=', name), ('parent_id', '=', False),
            ], limit=1) or cls.env['product.category'].create({'name': name})
        child = cls.env['product.category'].create({
            'name': 'Sony test models', 'parent_id': cls.brands['Sony'].id,
        })
        cls.sony = cls.env['product.product'].create({
            # Sony models are names while their references are EANs.
            'name': 'SAGEFULL.SONY', 'default_code': 'SAGEFULL-EAN', 'categ_id': child.id,
        })
        cls.digico = cls.env['product.product'].create({
            'name': 'Sage full DiGiCo', 'default_code': 'SAGEFULL-DIG',
            'categ_id': cls.brands['DiGiCo'].id,
        })
        cls.auvitran = cls.env['product.product'].create({
            'name': 'Sage full Auvitran', 'default_code': 'SAGEFULL-AUV',
            'categ_id': cls.brands['Auvitran'].id,
        })

    def _fixture(self):
        header = 'Almacén;Artículo;Nombre artículo;Lotes;Unidades;Precio;Total\n'
        sony = (
            '000;SONY-SAGEFULL-SONY;Sony model;;;;\n'
            'A.1;;;;;;\n'
            'A.2;;;;0,00;0,00;0,00\n'
            'AL1;;;;2,00;12,50;25,00\n'
            ';;;SAGEFULL-001;1,00;;\n'
            ';;;SAGEFULL-002;1,00;;\n'
        )
        return (header + sony +
            '000;DIG-SAGEFULL-DIG;Console;;;;\n'
            'AL1;;;;1.542,00;2,00;3.084,00\n'
            '000;AUV-SAGEFULL-AUV;Interface;;;;\n'
            'AL1;;;;1,00;3,00;3,00\n'
            ';;;S/N;1,00;;\n'
            '000;SAGEFULL-NO-PRODUCT;Unknown;;;;\n'
            'AL1;;;;4,00;1,00;4,00\n' + sony).encode('utf-8')

    def _wizard(self, raw=None, **values):
        vals = {'filename': 'full-company.csv', 'file_data': base64.b64encode(raw or self._fixture())}
        vals.update(values)
        return self.env['rms.stock.count.sage.import'].create(vals)

    def _snapshots(self, raw):
        import hashlib
        return self.env['rms.sage.snapshot'].search([
            ('file_hash', '=', hashlib.sha256(raw).hexdigest()),
            ('company_id', '=', self.env.company.id), ('sage_company_code', '=', '01'),
        ])

    def test_full_company_defaults_split_and_deduplicate(self):
        wizard = self._wizard()
        self.assertEqual(wizard.mode, 'replace')
        self.assertEqual(wizard.scope, 'all')
        self.assertFalse(wizard.brand_categ_id)
        result = wizard.action_import()
        # El cliente abre 'next' tal cual: sin 'views' Odoo 19 da
        # "action.views is undefined" tras una carga correcta.
        self.assertEqual(result['params']['next']['views'], [(False, 'list'), (False, 'form')])
        snapshots = self._snapshots(self._fixture())
        self.assertEqual(len(snapshots), 4)
        self.assertEqual(len(set(snapshots.mapped('file_hash'))), 1)
        self.assertTrue(all(snapshots.mapped('attachment')))
        sony = snapshots.filtered(lambda s: s.brand_categ_id == self.brands['Sony'])
        self.assertEqual(len(sony.line_ids), 2)
        self.assertEqual(set(sony.line_ids.mapped('serial')), {'SAGEFULL-001', 'SAGEFULL-002'})
        self.assertEqual(sony.line_ids.product_id, self.sony)
        self.assertEqual(sony.unit_count, 2)
        digico = snapshots.filtered(lambda s: s.brand_categ_id == self.brands['DiGiCo'])
        self.assertEqual(digico.unit_count, 1542)
        self.assertEqual(digico.line_ids.product_id, self.digico)
        auvitran = snapshots.filtered(lambda s: s.brand_categ_id == self.brands['Auvitran'])
        self.assertEqual(auvitran.unit_count, 1)
        self.assertFalse(auvitran.line_ids.serial)
        unknown = snapshots.filtered(lambda s: s.brand_categ_id.name == 'Sin marca')
        self.assertEqual(unknown.unmatched_count, 1)
        self.assertEqual(unknown.unit_count, 4)
        self.assertEqual(set(snapshots.line_ids.mapped('warehouse_code')), {'AL1'})

    def test_replace_only_brands_in_file(self):
        old = self.env['rms.sage.snapshot'].create([
            {'name': 'Old ' + name, 'brand_categ_id': brand.id}
            for name, brand in self.brands.items()
        ])
        for snapshot in old:
            snapshot.action_activate('add')
        self._wizard().action_import()
        absent = old.filtered(lambda s: s.brand_categ_id == self.brands['Absent Sage Test'])
        self.assertEqual(absent.state, 'current')
        self.assertEqual(set((old - absent).mapped('state')), {'replaced'})

    def test_brand_scope_rejects_multibrand_before_creating_versions(self):
        wizard = self._wizard(scope='brand', brand_categ_id=self.brands['Sony'].id)
        with self.assertRaisesRegex(UserError, 'Este archivo parece tener varias marcas'):
            wizard.action_import()
        self.assertFalse(self._snapshots(self._fixture()))

    def test_repeated_unserialized_blocks_are_not_summed(self):
        block = '000;DIG-SAGEFULL-DIG;Console;;;;\nAL1;;;;1.542,00;2,00;3.084,00\n'
        raw = ('Almacén;Artículo;Nombre artículo;Lotes;Unidades;Precio;Total\n' + block * 2).encode()
        self._wizard(raw).action_import()
        snapshot = self._snapshots(raw)
        self.assertEqual(len(snapshot.line_ids), 1)
        self.assertEqual(snapshot.unit_count, 1542)

    def test_learned_prefix_routes_unresolved_article(self):
        raw = (
            'Almacén;Artículo;Lotes;Unidades;Precio\n'
            'AL1;LEARN-SAGEFULL-DIG;;1;2\n'
            'AL1;LEARN-SAGEFULL-UNKNOWN;;3;2\n'
        ).encode()
        self.env['rms.sage.article.map'].create({
            'article_code': 'LEARN-SAGEFULL-DIG',
            'product_tmpl_id': self.digico.product_tmpl_id.id,
        })
        self._wizard(raw).action_import()
        snapshots = self._snapshots(raw)
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots.brand_categ_id, self.brands['DiGiCo'])
        self.assertEqual(snapshots.unmatched_count, 1)
        self.assertEqual(snapshots.unit_count, 4)

    def test_configured_prefix_routes_unknown_without_product(self):
        self.env['rms.sage.brand.prefix'].create({
            'prefix': 'CUSTOMFULL-', 'brand_categ_id': self.brands['Auvitran'].id,
        })
        raw = (
            'Almacén;Artículo;Lotes;Unidades;Precio\n'
            'AL1;D-CUSTOMFULL-UNKNOWN;;2;3\n'
        ).encode()
        self._wizard(raw).action_import()
        snapshot = self._snapshots(raw)
        self.assertEqual(snapshot.brand_categ_id, self.brands['Auvitran'])
        self.assertEqual(snapshot.unmatched_count, 1)
        self.assertEqual(snapshot.unit_count, 2)
        self.assertEqual(snapshot.line_ids.state, 'demo')

    def test_brand_ratio_counts_distinct_articles_not_serial_lines(self):
        rows = [
            'Almacén;Artículo;Lotes;Unidades;Precio',
            'AL1;SONY-SAGEFULL-SONY;;10;1',
        ]
        rows.extend(';;SAGEFULL-RATIO-%s;1;' % i for i in range(10))
        rows.append('AL1;DIG-SAGEFULL-DIG;;1;1')
        wizard = self._wizard(('\n'.join(rows)).encode(), scope='brand',
                              brand_categ_id=self.brands['Sony'].id)
        with self.assertRaisesRegex(UserError, 'Todas las marcas'):
            wizard.action_import()

    def test_serial_identity_is_unique_across_nonidentical_blocks(self):
        raw = (
            'Almacén;Artículo;Lotes;Unidades;Precio\n'
            'AL1;SONY-SAGEFULL-SONY;;1;2\n'
            ';;SAGEFULL-OVERLAP;1;\n'
            'AL1;SONY-SAGEFULL-SONY;;1;3\n'
            ';;SAGEFULL-OVERLAP;1;\n'
        ).encode()
        self._wizard(raw).action_import()
        self.assertEqual(len(self._snapshots(raw).line_ids), 1)

    def test_distinct_unserialized_blocks_consolidate_quantity_and_cost(self):
        first = '000;DIG-SAGEFULL-DIG;Console;;;;\nAL1;;;;2,00;10,00;20,00\n'
        second = '000;DIG-SAGEFULL-DIG;Console;;;;\nAL1;;;;3,00;20,00;60,00\n'
        raw = ('Almacén;Artículo;Nombre artículo;Lotes;Unidades;Precio;Total\n'
               + first + second + first).encode()
        self._wizard(raw).action_import()
        snapshot = self._snapshots(raw)
        self.assertEqual(len(snapshot.line_ids), 1)
        self.assertEqual(snapshot.unit_count, 5)
        self.assertAlmostEqual(snapshot.line_ids.sudo().cost, 16)
        self.assertAlmostEqual(snapshot.sudo().total_cost, 80)
