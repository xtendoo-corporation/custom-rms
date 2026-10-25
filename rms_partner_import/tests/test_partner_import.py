import base64
from types import SimpleNamespace
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged
from odoo.exceptions import UserError

from ..wizard import partner_import_wizard


@tagged('post_install', '-at_install')
class TestPartnerImport(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not cls.env.ref('custom.comerciales', raise_if_not_found=False):
            group = cls.env['res.groups'].create({'name': 'Comerciales'})
            cls.env['ir.model.data'].create({
                'module': 'custom', 'name': 'comerciales',
                'model': 'res.groups', 'res_id': group.id,
            })
        cls.Partner = cls.env['res.partner'].with_context(no_vat_validation=True)

    def _import(self, header, rows):
        # Simular únicamente la lectura del libro; el importador y el ORM son reales.
        book = SimpleNamespace(
            active=SimpleNamespace(iter_rows=lambda **kw: iter([header] + rows)),
            close=lambda: None,
        )
        reader = SimpleNamespace(load_workbook=lambda **kw: book)
        wizard = self.env['rms.partner.import.wizard'].create({
            'file': base64.b64encode(b'libro'), 'filename': 'contactos.xlsx',
        })
        with patch.object(partner_import_wizard, 'openpyxl', reader):
            return wizard.action_import()

    def test_missing_and_empty_email_preserve_existing(self):
        partner = self.Partner.create({'name': 'F6b Email', 'email': 'keep@example.com'})
        self._import(['nombre'], [['F6b Email']])
        self.assertEqual(partner.email, 'keep@example.com')
        self._import(['nombre', 'email'], [['F6b Email', '']])
        self.assertEqual(partner.email, 'keep@example.com')

    def test_duplicate_rows_complete_first(self):
        self._import(['nombre', 'email', 'ciudad'], [
            ['F6b Duplicado', '', 'Madrid'],
            [' f6b   duplicado ', 'new@example.com', 'Barcelona'],
        ])
        partners = self.Partner.search([('name', '=', 'F6b Duplicado')])
        self.assertEqual(len(partners), 1)
        self.assertEqual(partners.email, 'new@example.com')
        self.assertEqual(partners.city, 'Madrid')

    def test_vat_corrected_name_updates_archived(self):
        partner = self.Partner.create({
            'name': 'F6b Antiguo', 'vat': 'ES B-12345674', 'active': False,
        })
        self._import(['nombre', 'nif'], [['F6b Corregido', 'b12345674']])
        self.assertEqual(partner.name, 'F6b Corregido')
        self.assertFalse(partner.active)
        self.assertEqual(self.Partner.with_context(active_test=False).search_count([
            ('name', '=', 'F6b Corregido'),
        ]), 1)

    def test_ambiguous_match_reports_row(self):
        self.Partner.create([{'name': 'F6b Ambiguo'}, {'name': 'F6b Ambiguo'}])
        with self.assertRaisesRegex(UserError, 'Fila 2'):
            self._import(['nombre'], [['F6b Ambiguo']])

    def test_missing_name_reported(self):
        result = self._import(['nombre', 'email'], [['', 'skip@example.com']])
        self.assertIn('Filas sin nombre omitidas: 1', result['params']['message'])
        self.assertFalse(self.Partner.search([('email', '=', 'skip@example.com')]))

    def test_commercial_name_does_not_replace_missing_name(self):
        result = self._import(['nombre comercial'], [['F6b Solo comercial']])
        self.assertIn('Filas sin nombre omitidas: 1', result['params']['message'])
        self.assertFalse(self.Partner.search([('name', '=', 'F6b Solo comercial')]))

    def test_row_limit(self):
        with self.assertRaisesRegex(UserError, '50.000'):
            self._import(['nombre'], [['F6b Límite']] * 50001)

    def test_file_size_limit(self):
        wizard = self.env['rms.partner.import.wizard'].create({
            'filename': 'grande.xlsx',
            'file': base64.b64encode(b'x' * (20 * 1024 * 1024 + 1)),
        })
        with self.assertRaisesRegex(UserError, '20 MB'):
            wizard.action_import()
