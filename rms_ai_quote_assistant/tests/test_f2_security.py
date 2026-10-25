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

    def _warehouse_lots(self, state='second_hand'):
        product = self.env['product.product'].create({
            'name': 'Producto serializado R2Q', 'is_storable': True, 'tracking': 'serial',
        })
        lots = self.env['stock.lot']
        # Crear primero Y para que la selección sin almacén elija otro lote.
        for warehouse, price in (('Y', 90), ('X', 150), ('X', 180)):
            location = self.env['stock.location'].create({
                'name': 'Almacén R2Q %s' % warehouse, 'usage': 'internal',
            })
            lot = self.env['stock.lot'].create({
                'name': 'R2Q-%s-%s' % (warehouse, price), 'product_id': product.id,
                'company_id': self.env.company.id,
                'product_state_id': self.env.ref('rms_product_state.state_%s' % state).id,
                'custom_price': price,
            })
            self.env['stock.quant']._update_available_quantity(product, location, 1, lot_id=lot)
            lots |= lot
        return product, lots

    def test_confirm_preserves_warehouse_and_preview_serials(self):
        for state in ('second_hand', 'ex_demo'):
            with self.subTest(state=state):
                product, lots = self._warehouse_lots(state)
                preview = self.assistant._build_quote_preview(self.partner.id, [{
                    'product_id': product.id, 'quantity': 1,
                    'state': state, 'location': 'Almacén R2Q X',
                }])
                line = preview['lines'][0]
                self.assertEqual(line['location'], 'Almacén R2Q X')
                self.assertIn(line['lot_ids'][0], lots[1:].ids)
                # Incluso si cambia el orden de selección, se conserva el lote mostrado.
                with patch.object(type(self.assistant), '_pick_available_lots', return_value=lots[-1:].ids) as pick:
                    result = self.assistant.confirm_quote(self.partner.id, preview['lines'])
                self.assertEqual(result['type'], 'result')
                pick.assert_not_called()
                serial = self.env['sale.order'].browse(result['order_id']).order_line.serial_ids
                self.assertEqual(serial.lot_id.ids, line['lot_ids'])
                self.assertEqual(serial.price_unit, serial.lot_id.custom_price)

    def test_confirm_rejects_serial_from_other_warehouse(self):
        product, lots = self._warehouse_lots()
        before = self.env['sale.order'].search_count([])
        result = self.assistant.confirm_quote(self.partner.id, [{
            'product_id': product.id, 'quantity': 1, 'state': 'second_hand',
            'location': 'Almacén R2Q X', 'lot_ids': lots[:1].ids,
        }], new_opportunity_name='Oportunidad inválida R2Q')
        self.assertEqual(result['type'], 'error')
        self.assertNotIn(lots[0].name, result['text'])
        self.assertEqual(self.env['sale.order'].search_count([]), before)
        self.assertFalse(self.env['crm.lead'].search([('name', '=', 'Oportunidad inválida R2Q')]))

    def test_confirm_rejects_stale_preview_serials(self):
        product, lots = self._warehouse_lots()
        preview = self.assistant._build_quote_preview(self.partner.id, [{
            'product_id': product.id, 'quantity': 1,
            'state': 'second_hand', 'location': 'Almacén R2Q X',
        }])
        lot = self.env['stock.lot'].browse(preview['lines'][0]['lot_ids'])
        location = lot.location_id
        for change in ('state', 'stock', 'reservation'):
            with self.subTest(change=change), self.env.cr.savepoint():
                if change == 'state':
                    lot.product_state_id = self.env.ref('rms_product_state.state_new')
                elif change == 'stock':
                    self.env['stock.quant']._update_available_quantity(
                        product, location, -1, lot_id=lot,
                    )
                else:
                    order = self.env['sale.order'].create({'partner_id': self.partner.id})
                    order_line = self.env['sale.order.line'].create({
                        'order_id': order.id, 'product_id': product.id, 'product_uom_qty': 1,
                    })
                    self.env['sale.order.line.serial'].create({
                        'sale_order_line_id': order_line.id, 'lot_id': lot.id,
                    })
                before = self.env['sale.order'].search_count([])
                result = self.assistant.confirm_quote(self.partner.id, preview['lines'])
                self.assertEqual(result['type'], 'error')
                self.assertEqual(self.env['sale.order'].search_count([]), before)
                # Restaurar cada condición para comprobar las demás de forma independiente.
                if change == 'state':
                    lot.product_state_id = self.env.ref('rms_product_state.state_second_hand')
                elif change == 'stock':
                    self.env['stock.quant']._update_available_quantity(
                        product, location, 1, lot_id=lot,
                    )

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
