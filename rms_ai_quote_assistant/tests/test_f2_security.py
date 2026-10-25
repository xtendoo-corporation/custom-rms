from unittest.mock import Mock, patch

import requests

from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged('post_install', '-at_install')
class TestF2Security(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.assistant = cls.env['rms.ai.quote.assistant']
        cls.partner = cls.env['res.partner'].create({
            'name': 'Cliente F2', 'email': 'privado@example.com', 'phone': '123456789',
        })
        cls.product = cls.env['product.product'].create({'name': 'Producto F2'})
        cls.other_product = cls.env['product.product'].create({'name': 'Otro F2'})
        cls.lot = cls.env['stock.lot'].create({
            'name': 'Serie ajena F2', 'product_id': cls.other_product.id,
            'company_id': cls.env.company.id,
        })
        group = cls.env.ref('custom.comerciales', raise_if_not_found=False)
        if not group:
            group = cls.env['res.groups'].create({'name': 'Comerciales'})
            cls.env['ir.model.data'].create({
                'module': 'custom', 'name': 'comerciales',
                'model': 'res.groups', 'res_id': group.id,
            })
        cls.salesperson = new_test_user(
            cls.env, login='f2_quote_sales',
            groups='base.group_user,sales_team.group_sale_salesman,custom.comerciales',
        )

        cls.partner.user_id = cls.salesperson

    def test_foreign_product_lot_rejected(self):
        before = self.env['sale.order'].search_count([])
        result = self.assistant.confirm_quote(self.partner.id, [{
            'product_id': self.product.id, 'quantity': 1,
            'state': 'new', 'lot_ids': self.lot.ids,
        }])
        self.assertEqual(result['type'], 'error')
        self.assertEqual(self.env['sale.order'].search_count([]), before)

    def test_creation_uses_recalculated_preview(self):
        preview = {'lines': [{'product_id': self.product.id, 'quantity': 2, 'state': 'new'}]}
        with patch.object(type(self.assistant), '_build_quote_preview', return_value=preview):
            result = self.assistant.confirm_quote(self.partner.id, [{
                'product_id': self.other_product.id, 'quantity': 99,
            }])
        self.assertEqual(result['type'], 'result')
        line = self.env['sale.order'].browse(result['order_id']).order_line
        self.assertEqual(line.product_id, self.product)
        self.assertEqual(line.product_uom_qty, 2)

    def test_gemini_key_only_in_header(self):
        response = Mock(ok=True)
        response.json.return_value = {}
        with patch.object(requests, 'post', return_value=response) as post:
            self.assistant._call_gemini('secret-f2', 'gemini-test', '', [], [])
        args, kwargs = post.call_args
        self.assertNotIn('secret-f2', args[0])
        self.assertNotIn('params', kwargs)
        self.assertEqual(kwargs['headers']['x-goog-api-key'], 'secret-f2')

    def test_contact_data_not_in_prompt_or_commercial_preview(self):
        prompt, _hint = self.assistant._build_system_prompt()
        self.assertNotIn(self.partner.email, prompt)
        preview = self.assistant.with_user(self.salesperson)._build_quote_preview(
            self.partner.id, [{'product_id': self.product.id, 'quantity': 1}],
        )
        self.assertFalse(preview['partner_email'])
        self.assertNotIn(self.partner.email, self.assistant._format_preview_text(preview))

    def test_savepoint_removes_new_opportunity_on_failure(self):
        # Un fallo de creación no debe borrar cambios anteriores de la petición.
        marker = self.env['res.partner'].create({'name': 'Marcador F2'})
        with patch.object(type(self.env['sale.order']), 'create', side_effect=ValueError('detalle privado')):
            result = self.assistant.confirm_quote(
                self.partner.id, [{'product_id': self.product.id, 'quantity': 1}],
                new_opportunity_name='Oportunidad fallida F2',
            )
        self.assertEqual(result['type'], 'error')
        self.assertNotIn('detalle privado', result['text'])
        self.assertTrue(marker.exists())
        self.assertFalse(self.env['crm.lead'].search([('name', '=', 'Oportunidad fallida F2')]))
