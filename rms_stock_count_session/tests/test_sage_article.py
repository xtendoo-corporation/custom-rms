# -*- coding: utf-8 -*-
import base64
from io import BytesIO

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSageArticleMaster(TransactionCase):

    HEADER = ['Código', 'Nombre', 'Marca', 'Nombre marca', 'Familia', 'Nombre familia',
              'Subfamilia', 'Nombre subfamilia', 'Código alternativo', 'Baja', 'Fecha baja']

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.meyer = cls.env['product.category'].create({'name': 'Meyer Sound Test'})
        cls.harvey = cls.env['product.category'].create({'name': 'DSPecialists (Harvey Test)'})

    def _xlsx(self, rows):
        from openpyxl import Workbook
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(self.HEADER)
        for row in rows:
            sheet.append(row)
        stream = BytesIO()
        workbook.save(stream)
        return stream.getvalue()

    def _load_master(self, rows, filename='maestro.xlsx'):
        raw = self._xlsx(rows) if filename.endswith('xlsx') else rows
        return self.env['rms.sage.article.import'].create({
            'filename': filename, 'file_data': base64.b64encode(raw)}).action_import()

    def _master_rows(self):
        return [
            ['0933800104', 'LYON-M Linear Line Array', 'MEY', 'MEYER SOUND TEST', 'MEYER', 'Meyer',
             '', '', None, 'False', None],
            ['D-0933800104', 'LYON-M (demo)', 'MEY', 'MEYER SOUND TEST', 'EXDEM', 'Ex-Demo',
             '', '', None, 'False', None],
            ['2M-ZZTEST-1', 'Caja usada', 'ZZB', 'ZZ BRAND NUEVA', 'RMSOC', 'RMS Ocasión',
             '', '', None, 'True', '01/01/2024'],
            ['HAR-TEST-1', 'Mic', 'HAR', 'HARVEY TEST', 'HAR', 'Harvey', '', '', None, 'False', None],
            ['TIENDA-X1', 'Funda', 'TIE', 'TIENDA', 'TIEND', 'Tienda', '', '', None, 'False', None],
        ]

    def test_import_creates_articles_and_maps_brands(self):
        result = self._load_master(self._master_rows())
        self.assertIn('Nuevos: 5', result['params']['message'])
        Article = self.env['rms.sage.article']
        lyon = Article.search([('code', '=', '0933800104')])
        self.assertEqual(lyon.brand_categ_id, self.meyer, 'Mayúsculas/espacios no deben crear otra marca')
        self.assertEqual(Article.search([('code', '=', 'D-0933800104')]).state_prefix, 'demo')
        used = Article.search([('code', '=', '2M-ZZTEST-1')])
        self.assertEqual(used.state_prefix, '2mano')
        self.assertTrue(used.discontinued)
        self.assertEqual(used.brand_categ_id.name, 'Zz Brand Nueva')
        self.assertFalse(used.brand_categ_id.parent_id)
        self.assertEqual(Article.search([('code', '=', 'HAR-TEST-1')]).brand_categ_id, self.harvey)
        # TIENDA queda como marca aparte, no mezclada con otras.
        tienda = Article.search([('code', '=', 'TIENDA-X1')]).brand_categ_id
        self.assertEqual(tienda.name, 'Tienda')

    def test_reimport_updates_without_duplicates(self):
        self._load_master(self._master_rows())
        rows = self._master_rows()
        rows[0][1] = 'LYON-M nuevo nombre'
        result = self._load_master(rows)
        self.assertIn('Nuevos: 0 · Actualizados: 1', result['params']['message'])
        self.assertEqual(self.env['rms.sage.article'].search_count([('code', '=', '0933800104')]), 1)

    def test_csv_master(self):
        raw = ('Código;Nombre;Marca;Nombre marca;Familia;Nombre familia;Baja\n'
               'CSV-ART-1;Algo;MEY;Meyer Sound Test;MEYER;Meyer;False\n').encode('utf-8')
        self._load_master(raw, filename='maestro.csv')
        article = self.env['rms.sage.article'].search([('code', '=', 'CSV-ART-1')])
        self.assertEqual(article.brand_categ_id, self.meyer)

    def test_stock_import_uses_master_brand_not_sin_marca(self):
        self._load_master(self._master_rows())
        raw = ('Almacén;Artículo;Nombre artículo;Lotes;Unidades\n'
               '000;0933800104;LYON-M;;\n'
               'AL1;;;;1,00\n'
               ';;;MSTEST-SN-1;1,00\n'
               '000;D-0933800104;LYON-M demo;;\n'
               'AL1;;;;1,00\n'
               ';;;MSTEST-SN-2;1,00\n').encode('utf-8')
        self.env['rms.stock.count.sage.import'].create({
            'filename': 'existencias.csv', 'file_data': base64.b64encode(raw)}).action_import()
        lines = self.env['rms.sage.stock.line'].search([('serial', 'in', ['MSTEST-SN-1', 'MSTEST-SN-2'])])
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines.brand_categ_id, self.meyer)
        self.assertEqual(set(lines.mapped('state')), {'nuevo', 'demo'})

    def test_prepare_products_takes_master_name_and_brand(self):
        self._load_master(self._master_rows())
        raw = ('Almacén;Artículo;Nombre artículo;Lotes;Unidades\n'
               '000;D-0933800104;nombre corto;;\n'
               'AL1;;;;1,00\n'
               ';;;MSTEST-SN-3;1,00\n').encode('utf-8')
        self.env['rms.stock.count.sage.import'].create({
            'filename': 'existencias2.csv', 'file_data': base64.b64encode(raw)}).action_import()
        line = self.env['rms.sage.stock.line'].search([('serial', '=', 'MSTEST-SN-3')])
        # Simula una carga anterior al maestro: la línea quedó "Sin marca".
        line.brand_categ_id = self.env['product.category'].create({'name': 'Sin marca test'})
        wizard = self.env['rms.sage.product.prepare'].create({'line_ids': [(6, 0, line.ids)]})
        wizard.action_create_products()
        template = self.env['product.template'].search([('default_code', '=', '0933800104')])
        self.assertEqual(template.categ_id, self.meyer)
        self.assertEqual(template.name, 'LYON-M Linear Line Array')
        self.assertEqual(template.tracking, 'serial')
