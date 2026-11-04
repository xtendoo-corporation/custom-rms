from lxml import etree

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests import Form
from odoo.tests.common import TransactionCase, new_test_user


@tagged('post_install', '-at_install')
class TestServerRestrictions(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not cls.env.ref('custom.comerciales', raise_if_not_found=False):
            group = cls.env['res.groups'].create({'name': 'Comerciales prueba F1'})
            cls.env['ir.model.data'].create({
                'module': 'custom', 'name': 'comerciales',
                'model': 'res.groups', 'res_id': group.id,
            })
        if not cls.env['ir.rule'].search_count([
            ('model_id', '=', cls.env.ref('base.model_res_partner').id),
            ('name', '=', 'CUSTOM/Contactos propios'),
        ]):
            cls.env['ir.rule'].create({
                'name': 'CUSTOM/Contactos propios (prueba)',
                'model_id': cls.env.ref('base.model_res_partner').id,
                'groups': [(6, 0, cls.env.ref('custom.comerciales').ids)],
                'domain_force': "['|', ('user_id', '=', user.id), ('user_ids', '!=', False)]",
                'perm_read': True,
                'perm_write': True,
                'perm_create': True,
                'perm_unlink': False,
            })
        cls.user = new_test_user(cls.env, login='f1_rms_ventas_restriccion_comerciales', groups='base.group_user,sales_team.group_sale_salesman,custom.comerciales')
        cls.partner = cls.env['res.partner'].create({'name': 'Cliente F1', 'user_id': cls.user.id})
        cls.product = cls.env['product.product'].create({'name': 'Producto F1', 'list_price': 100})
        cls.order = cls.env['sale.order'].create({'partner_id': cls.partner.id, 'user_id': cls.user.id})
        cls.line = cls.env['sale.order.line'].create({'order_id': cls.order.id, 'product_id': cls.product.id})

    def test_write_ignores_protected_fields(self):
        fields = [f for f in ('price_unit', 'discount', 'discount1', 'discount2', 'discount3') if f in self.line._fields]
        before = {f: self.line[f] for f in fields}
        tax = self.env['account.tax'].create({'name': 'IVA F1', 'amount': 21, 'type_tax_use': 'sale'})
        self.line.tax_ids = tax
        taxes = self.line.tax_ids
        self.line.with_user(self.user).write(dict({f: 95 for f in fields}, tax_ids=[(6, 0, [])]))
        self.assertEqual({f: self.line[f] for f in fields}, before)
        self.assertEqual(self.line.tax_ids, taxes)
        fiscal = self.env['account.fiscal.position'].create({'name': 'Posición F1'})
        pricelist = self.env['product.pricelist'].create({'name': 'Tarifa F1'})
        old = (self.order.fiscal_position_id, self.order.pricelist_id)
        self.order.with_user(self.user).write({'fiscal_position_id': fiscal.id, 'pricelist_id': pricelist.id})
        self.assertEqual((self.order.fiscal_position_id, self.order.pricelist_id), old)

    def test_create_ignores_protected_fields(self):
        line = self.env['sale.order.line'].with_user(self.user).create({
            'order_id': self.order.id, 'product_id': self.product.id,
            'price_unit': 1, 'discount': 95,
        })
        self.assertEqual(line.price_unit, self.line.price_unit)
        self.assertEqual(line.discount, self.line.discount)

    def test_full_edit_and_actions(self):
        for action in ('action_update_prices', 'action_update_taxes', 'action_open_discount_wizard'):
            with self.assertRaises(AccessError):
                getattr(self.order.with_user(self.user), action)()
        self.user.group_ids |= self.env.ref('rms_ventas_restriccion_comerciales.group_comerciales_quotation_full_edit')
        self.line.with_user(self.user).write({'price_unit': 1, 'discount': 95, 'tax_ids': [(6, 0, [])]})
        self.assertEqual(self.line.price_unit, 1)
        self.assertEqual(self.line.discount, 95)
        self.assertFalse(self.line.tax_ids)
        fiscal = self.env['account.fiscal.position'].create({'name': 'Posición autorizada F1'})
        self.order.with_user(self.user).write({'fiscal_position_id': fiscal.id})
        self.assertEqual(self.order.fiscal_position_id, fiscal)

    def _protected_defaults(self):
        tax = self.env['account.tax'].create({
            'name': 'IVA contexto R1C', 'amount': 7, 'type_tax_use': 'sale',
        })
        fiscal = self.env['account.fiscal.position'].create({'name': 'Posición contexto R1C'})
        pricelist = self.env['product.pricelist'].create({'name': 'Tarifa contexto R1C'})
        defaults = {
            'default_price_unit': 1, 'default_discount': 95,
            'default_tax_ids': [(6, 0, tax.ids)],
            'default_pricelist_id': pricelist.id,
            'default_fiscal_position_id': fiscal.id,
        }
        for field in ('discount1', 'discount2', 'discount3'):
            if field in self.line._fields:
                defaults['default_' + field] = 95
        return defaults, tax, fiscal, pricelist

    def _assert_computed_line_values(self, line):
        for field in ('price_unit', 'discount', 'discount1', 'discount2', 'discount3', 'tax_ids'):
            if field in line._fields:
                self.assertEqual(line[field], self.line[field], field)

    def test_create_line_ignores_context_defaults(self):
        defaults, _tax, _fiscal, _pricelist = self._protected_defaults()
        line = self.env['sale.order.line'].with_user(self.user).with_context(defaults).create({
            'order_id': self.order.id, 'product_id': self.product.id,
        })
        self._assert_computed_line_values(line)

    def test_create_order_ignores_context_defaults_and_nested_lines(self):
        defaults, _tax, _fiscal, _pricelist = self._protected_defaults()
        order = self.env['sale.order'].with_user(self.user).with_context(defaults).create({
            'partner_id': self.partner.id, 'user_id': self.user.id,
            'order_line': [(0, 0, {'product_id': self.product.id})],
        })
        self.assertEqual(order.pricelist_id, self.order.pricelist_id)
        self.assertEqual(order.fiscal_position_id, self.order.fiscal_position_id)
        self.assertEqual(len(order.order_line), 1)
        self._assert_computed_line_values(order.order_line)

    def test_full_edit_preserves_context_defaults(self):
        self.user.group_ids |= self.env.ref(
            'rms_ventas_restriccion_comerciales.group_comerciales_quotation_full_edit'
        )
        defaults, tax, fiscal, pricelist = self._protected_defaults()
        # Evitar que el descuento triple recalcule el descuento global en esta prueba.
        for field in ('discount1', 'discount2', 'discount3'):
            defaults.pop('default_' + field, None)
        order = self.env['sale.order'].with_user(self.user).with_context(defaults).create({
            'partner_id': self.partner.id, 'user_id': self.user.id,
        })
        self.assertEqual(order.pricelist_id, pricelist)
        self.assertEqual(order.fiscal_position_id, fiscal)
        line = self.env['sale.order.line'].with_user(self.user).with_context(defaults).create({
            'order_id': order.id, 'product_id': self.product.id,
        })
        self.assertEqual(line.price_unit, 1)
        self.assertEqual(line.discount, 95)
        self.assertEqual(line.tax_ids, tax)

    def test_pricelist_group_keeps_pricelist_and_discounts(self):
        self.user.group_ids |= self.env.ref('rms_ventas_restriccion_comerciales.group_comerciales_pricelist')
        pricelist = self.env['product.pricelist'].create({
            'name': 'Tarifa tipo de cliente',
        })
        order = self.env['sale.order'].with_user(self.user).create({
            'partner_id': self.partner.id, 'user_id': self.user.id,
            'pricelist_id': pricelist.id,
            'order_line': [(0, 0, {'product_id': self.product.id})],
        })
        self.assertEqual(order.pricelist_id, pricelist)
        other = self.env['product.pricelist'].create({'name': 'Otra tarifa'})
        order.with_user(self.user).write({'pricelist_id': other.id})
        self.assertEqual(order.pricelist_id, other)
        order.with_user(self.user).action_update_prices()
        # Sigue sin poder tocar precios ni descuentos a mano.
        order.order_line.with_user(self.user).write({'discount': 50})
        self.assertNotEqual(order.order_line.discount, 50)
        with self.assertRaises(AccessError):
            order.with_user(self.user).action_update_taxes()

    def test_only_own_customers(self):
        other = self.env['res.partner'].create({'name': 'Cliente de otro comercial'})
        with self.assertRaises(ValidationError):
            self.env['sale.order'].with_user(self.user).create({'partner_id': other.id})
        with self.assertRaises(ValidationError):
            self.order.with_user(self.user).write({'partner_id': other.id})
        self.assertEqual(self.order.partner_id, self.partner)
        # Un contacto de la empresa de su cliente también es cliente suyo.
        contact = self.env['res.partner'].create({'name': 'Contacto F1', 'parent_id': self.partner.id})
        contact.user_id = False
        order = self.env['sale.order'].with_user(self.user).create({'partner_id': contact.id})
        self.assertEqual(order.partner_id, contact)
        # Otros usuarios de ventas no tienen esta restricción, ni los comerciales
        # con permiso para presupuestar a cualquier cliente.
        self.env['sale.order'].create({'partner_id': other.id})
        self.user.group_ids |= self.env.ref('rms_ventas_restriccion_comerciales.group_comerciales_all_customers')
        order = self.env['sale.order'].with_user(self.user).create({'partner_id': other.id})
        self.assertEqual(order.partner_id, other)

    def test_shared_customers_between_salespeople(self):
        # Traspaso de cartera: este comercial lleva también los clientes de otro.
        other_user = new_test_user(self.env, login='f1_comercial_traspaso', groups='base.group_user,sales_team.group_sale_salesman,custom.comerciales')
        other_partner = self.env['res.partner'].create({
            'name': 'Cliente traspasado F1', 'is_company': True, 'user_id': other_user.id,
        })
        contact = self.env['res.partner'].create({'name': 'Contacto traspasado F1', 'parent_id': other_partner.id})
        contact.user_id = False
        other_order = self.env['sale.order'].with_user(other_user).create({'partner_id': other_partner.id})
        other_lead = self.env['crm.lead'].create({'name': 'Oportunidad F1', 'user_id': other_user.id})
        Partner = self.env['res.partner'].with_user(self.user)
        partners = other_partner | contact
        with self.assertRaises(ValidationError):
            self.env['sale.order'].with_user(self.user).create({'partner_id': other_partner.id})
        self.assertFalse(Partner.search([('id', 'in', partners.ids), ('rms_is_own_customer', '=', True)]))
        self.assertFalse(self.env['sale.order'].with_user(self.user).search([('id', '=', other_order.id)]))
        self.assertFalse(self.env['crm.lead'].with_user(self.user).search([('id', '=', other_lead.id)]))

        self.user.rms_shared_customer_user_ids = other_user
        for partner in partners:
            order = self.env['sale.order'].with_user(self.user).create({'partner_id': partner.id})
            self.assertEqual(order.partner_id, partner)
        self.assertEqual(Partner.search([('id', 'in', partners.ids), ('rms_is_own_customer', '=', True)]), partners)
        self.assertEqual(Partner.search([('id', 'in', (partners | self.partner).ids), ('rms_is_own_customer', '=', False)]), Partner)
        self.assertTrue(other_partner.with_user(self.user).rms_is_own_customer)
        self.assertEqual(self.env['sale.order'].with_user(self.user).search([('id', '=', other_order.id)]), other_order)
        self.assertEqual(self.env['crm.lead'].with_user(self.user).search([('id', '=', other_lead.id)]), other_lead)
        # Sigue teniendo sus propios clientes, y el otro comercial no gana nada.
        self.env['sale.order'].with_user(self.user).create({'partner_id': self.partner.id})
        with self.assertRaises(ValidationError):
            self.env['sale.order'].with_user(other_user).create({'partner_id': self.partner.id})
        self.assertFalse(self.env['sale.order'].with_user(other_user).search([('id', '=', self.order.id)]))

    def test_partner_dropdown_only_own_customers(self):
        arch = self.env['sale.order'].with_user(self.user).get_view(view_type='form')['arch']
        self.assertIn("('rms_is_own_customer', '=', True)", arch)
        arch = self.env['sale.order'].get_view(view_type='form')['arch']
        self.assertNotIn("('rms_is_own_customer', '=', True)", arch)
        self.user.group_ids |= self.env.ref('rms_ventas_restriccion_comerciales.group_comerciales_all_customers')
        arch = self.env['sale.order'].with_user(self.user).get_view(view_type='form')['arch']
        self.assertNotIn("('rms_is_own_customer', '=', True)", arch)

    def test_pricelist_readonly_without_pricelist_group(self):
        def pricelist_node():
            arch = self.env['sale.order'].with_user(self.user).get_view(view_type='form')['arch']
            return etree.fromstring(arch).xpath("//field[@name='pricelist_id']")[0]
        node = pricelist_node()
        self.assertEqual(node.get('readonly'), '1')
        self.assertNotEqual(node.get('invisible'), '1')
        self.user.group_ids |= self.env.ref('rms_ventas_restriccion_comerciales.group_comerciales_pricelist')
        self.assertNotEqual(pricelist_node().get('readonly'), '1')

    def test_order_takes_customer_pricelist(self):
        pricelist = self.env['product.pricelist'].create({'name': 'Tarifa del cliente'})
        self.partner.property_product_pricelist = pricelist
        order = self.env['sale.order'].with_user(self.user).create({'partner_id': self.partner.id})
        self.assertEqual(order.pricelist_id, pricelist)

    def test_lines_take_pricelist_triple_discount(self):
        if 'discount1' not in self.env['product.pricelist.item']._fields:
            self.skipTest('product_pricelist_triple_discount no instalado')
        pricelist = self.env['product.pricelist'].create({
            'name': 'Touring prueba',
            'item_ids': [(0, 0, {
                'applied_on': '3_global', 'compute_price': 'triple_discount',
                'discount1': 10, 'percent_price': 10, 'price_discount': 10,
            })],
        })
        self.partner.property_product_pricelist = pricelist
        order = self.env['sale.order'].with_user(self.user).create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {'product_id': self.product.id})],
        })
        line = order.order_line
        self.assertEqual(order.pricelist_id, pricelist)
        self.assertEqual(line.discount1, 10)
        self.assertAlmostEqual(line.price_subtotal, 90)
        line.with_user(self.user).write({'product_uom_qty': 2})
        self.assertEqual(line.discount1, 10)
        self.assertAlmostEqual(line.price_subtotal, 180)

    def test_discount_columns_visible_readonly(self):
        if 'discount1' not in self.env['sale.order.line']._fields:
            self.skipTest('sale_triple_discount no instalado')
        # Con el grupo «Descuentos en líneas» las columnas siempre se ven; sin
        # él, la vista de un comercial debe seguir mostrándolas en solo lectura.
        admin_arch = self.env['sale.order'].get_view(view_type='form')['arch']
        xpath = "//field[@name='order_line']//field[@name='discount1']"
        if not etree.fromstring(admin_arch).xpath(xpath):
            self.skipTest('la vista de presupuesto no tiene la columna discount1')
        arch = self.env['sale.order'].with_user(self.user).get_view(view_type='form')['arch']
        nodes = etree.fromstring(arch).xpath(xpath)
        self.assertTrue(nodes)
        for node in nodes:
            self.assertEqual(node.get('readonly'), '1')

    def test_comercial_can_delete_own_quotations(self):
        order = self.env['sale.order'].with_user(self.user).create({
            'partner_id': self.partner.id, 'user_id': self.user.id,
            'order_line': [(0, 0, {'product_id': self.product.id})],
        })
        order.with_user(self.user).unlink()
        self.assertFalse(order.exists())
        # No puede borrar presupuestos de otro comercial.
        other_user = new_test_user(self.env, login='f1_otro_comercial', groups='base.group_user,sales_team.group_sale_salesman_all_leads,custom.comerciales')
        with self.assertRaises(AccessError):
            self.order.with_user(other_user).unlink()
        self.assertTrue(self.order.exists())
        # Ni los ya enviados o confirmados (Odoo exige cancelarlos antes).
        self.order.state = 'sent'
        with self.assertRaises(UserError):
            self.order.with_user(self.user).unlink()

    def test_comercial_can_delete_own_opportunities(self):
        lead = self.env['crm.lead'].with_user(self.user).create({
            'name': 'Oportunidad F1', 'type': 'opportunity',
            'partner_id': self.partner.id, 'user_id': self.user.id,
        })
        lead.with_user(self.user).unlink()
        self.assertFalse(lead.exists())
        # No puede borrar oportunidades de otro comercial.
        other_lead = self.env['crm.lead'].create({
            'name': 'Oportunidad de otro', 'type': 'opportunity', 'user_id': self.user.id,
        })
        other_user = new_test_user(self.env, login='f1_otro_comercial_crm', groups='base.group_user,sales_team.group_sale_salesman_all_leads,custom.comerciales')
        with self.assertRaises(AccessError):
            other_lead.with_user(other_user).unlink()
        self.assertTrue(other_lead.exists())

    def test_assigned_lead_customer_readable_and_chatter_works(self):
        # INC-00007: el administrador asigna al comercial una oportunidad de un
        # cliente que no es suyo, con un seguidor que tampoco puede leer.
        other_user = new_test_user(self.env, login='f1_comercial_inc7', groups='base.group_user,sales_team.group_sale_salesman,custom.comerciales')
        customer = self.env['res.partner'].create({
            'name': 'Cliente ajeno F1', 'email': 'ajeno@example.com', 'user_id': other_user.id,
        })
        follower = self.env['res.partner'].create({
            'name': 'Seguidor ajeno F1', 'email': 'seguidor@example.com', 'user_id': other_user.id,
        })
        lead = self.env['crm.lead'].create({
            'name': 'Oportunidad INC-00007', 'type': 'opportunity',
            'partner_id': customer.id, 'user_id': self.user.id,
        })
        lead.message_subscribe(partner_ids=follower.ids)
        order = self.env['sale.order'].create({'partner_id': customer.id, 'user_id': self.user.id})
        order.message_subscribe(partner_ids=follower.ids)
        unrelated = self.env['res.partner'].create({'name': 'Cliente sin documentos F1', 'user_id': other_user.id})
        lead.with_user(self.user).message_post(
            body='Hola', message_type='comment', subtype_xmlid='mail.mt_comment', partner_ids=unrelated.ids,
        )

        Partner = self.env['res.partner'].with_user(self.user)
        # El cliente de su oportunidad se puede leer, pero no editar.
        self.assertEqual(customer.with_user(self.user).name, 'Cliente ajeno F1')
        with self.assertRaises(AccessError):
            customer.with_user(self.user).write({'name': 'Cambiado'})
        # Los demás contactos ajenos siguen ocultos.
        self.assertFalse(Partner.search([('id', 'in', (follower | unrelated).ids)]))
        # Sigue sin poder presupuestarle: no es cliente suyo.
        self.assertFalse(customer.with_user(self.user).rms_is_own_customer)
        with self.assertRaises(ValidationError):
            self.env['sale.order'].with_user(self.user).create({'partner_id': customer.id})

        # El chatter calcula los destinatarios sin AccessError y no expone los
        # contactos que no puede leer.
        for record in (lead, order):
            record.invalidate_recordset()
            self.env['res.partner'].invalidate_model()
            suggested = record.with_user(self.user)._message_get_suggested_recipients(
                reply_discussion=True, no_create=True,
            )
            partner_ids = {r['partner_id'] for r in suggested if r['partner_id']}
            self.assertFalse(partner_ids & set((follower | unrelated).ids))

        # Sin la oportunidad ni el presupuesto asignados, deja de verlo.
        lead.user_id = other_user
        order.user_id = other_user
        self.assertFalse(Partner.search([('id', '=', customer.id)]))

    def test_quotation_from_assigned_opportunity_of_other_customer(self):
        # INC-00007: el administrador asigna al comercial una oportunidad de un
        # cliente ajeno; desde ella puede hacerle presupuestos e imprimirlos.
        other_user = new_test_user(self.env, login='f1_comercial_inc7b', groups='base.group_user,sales_team.group_sale_salesman,custom.comerciales')
        company = self.env['res.partner'].create({'name': 'Empresa ajena F1', 'is_company': True, 'user_id': other_user.id})
        contact = self.env['res.partner'].create({'name': 'Contacto ajeno F1', 'parent_id': company.id})
        invoice = self.env['res.partner'].create({'name': 'Factura ajena F1', 'parent_id': company.id, 'type': 'invoice'})
        other_company = self.env['res.partner'].create({'name': 'Otra empresa ajena F1', 'is_company': True, 'user_id': other_user.id})
        lead = self.env['crm.lead'].create({
            'name': 'Oportunidad asignada F1', 'type': 'opportunity',
            'partner_id': company.id, 'user_id': self.user.id,
        })
        SaleOrder = self.env['sale.order'].with_user(self.user)

        # Como en la interfaz: botón «Nuevo presupuesto» de la oportunidad.
        with Form(SaleOrder.with_context(**lead._prepare_opportunity_quotation_context())) as form:
            form.partner_id = company
        ui_order = form.save()
        self.assertEqual((ui_order.partner_id, ui_order.user_id, ui_order.opportunity_id), (company, self.user, lead))
        # Con la oportunidad en los valores o en el contexto.
        order = SaleOrder.create({'partner_id': company.id, 'opportunity_id': lead.id})
        self.assertEqual(order.partner_invoice_id, invoice)
        self.assertEqual(order.partner_invoice_id.name, 'Factura ajena F1')
        order2 = SaleOrder.with_context(default_opportunity_id=lead.id).create({'partner_id': contact.id})
        self.assertEqual(order2.opportunity_id, lead)
        order.write({'partner_id': contact.id})
        self.env['sale.order.line'].create({'order_id': order.id, 'product_id': self.product.id})
        self.env.invalidate_all()
        self.env['ir.actions.report'].with_user(self.user)._render_qweb_html('sale.action_report_saleorder', order.ids)
        # Los contactos de la empresa se leen, pero no se editan.
        with self.assertRaises(AccessError):
            invoice.with_user(self.user).write({'name': 'Cambiado'})

        # Sigue bloqueado: sin oportunidad, otra empresa, o al cambiar a otro cliente.
        with self.assertRaises(ValidationError):
            SaleOrder.create({'partner_id': company.id})
        with self.assertRaises(ValidationError):
            SaleOrder.create({'partner_id': other_company.id, 'opportunity_id': lead.id})
        with self.assertRaises(ValidationError):
            order.write({'partner_id': other_company.id})
        self.assertFalse(self.env['res.partner'].with_user(self.user).search([('id', '=', other_company.id)]))
        # Ni con una oportunidad que no es suya.
        lead2 = self.env['crm.lead'].create({
            'name': 'Oportunidad de otro F1', 'type': 'opportunity',
            'partner_id': company.id, 'user_id': other_user.id,
        })
        with self.assertRaises(ValidationError):
            SaleOrder.create({'partner_id': company.id, 'opportunity_id': lead2.id})

    def test_opportunities_only_own_customers(self):
        Lead = self.env['crm.lead'].with_user(self.user)
        other_user = new_test_user(self.env, login='f1_comercial_oport', groups='base.group_user,sales_team.group_sale_salesman,custom.comerciales')
        other = self.env['res.partner'].create({'name': 'Cliente ajeno oportunidad F1', 'user_id': other_user.id})
        # Con un cliente ajeno no puede crearla, tampoco desde la ficha del cliente.
        with self.assertRaises(ValidationError):
            Lead.create({'name': 'Oportunidad ajena F1', 'type': 'opportunity', 'partner_id': other.id})
        with self.assertRaises(ValidationError):
            Lead.with_context(default_partner_id=other.id).create({'name': 'Desde la ficha F1', 'type': 'opportunity'})
        # Con su cliente, un contacto de su empresa o sin cliente, sí.
        contact = self.env['res.partner'].create({'name': 'Contacto oportunidad F1', 'parent_id': self.partner.id})
        contact.user_id = False
        lead = Lead.create({'name': 'Oportunidad propia F1', 'type': 'opportunity', 'partner_id': self.partner.id})
        Lead.create({'name': 'Oportunidad contacto F1', 'type': 'opportunity', 'partner_id': contact.id})
        Lead.create({'name': 'Oportunidad sin cliente F1', 'type': 'opportunity'})
        # No puede cambiar su oportunidad a un cliente ajeno.
        with self.assertRaises(ValidationError):
            lead.with_user(self.user).write({'partner_id': other.id})
        self.assertEqual(lead.partner_id, self.partner)
        # El administrador no tiene restricción, ni el comercial con el
        # permiso de presupuestar a cualquier cliente.
        self.env['crm.lead'].create({'name': 'Oportunidad admin F1', 'partner_id': other.id, 'user_id': self.user.id})
        self.user.group_ids |= self.env.ref('rms_ventas_restriccion_comerciales.group_comerciales_all_customers')
        lead = Lead.create({'name': 'Oportunidad permitida F1', 'type': 'opportunity', 'partner_id': other.id})
        self.assertEqual(lead.partner_id, other)

    def test_opportunity_assigned_by_admin_of_other_customer(self):
        # El administrador asigna al comercial una oportunidad de un cliente
        # ajeno: puede trabajarla y cambiar a otro contacto de esa empresa,
        # pero no a otra empresa ajena.
        other_user = new_test_user(self.env, login='f1_comercial_oport2', groups='base.group_user,sales_team.group_sale_salesman,custom.comerciales')
        company = self.env['res.partner'].create({'name': 'Empresa asignada F1', 'is_company': True, 'user_id': other_user.id})
        contact = self.env['res.partner'].create({'name': 'Contacto asignado F1', 'parent_id': company.id})
        other_company = self.env['res.partner'].create({'name': 'Otra empresa F1', 'is_company': True, 'user_id': other_user.id})
        lead = self.env['crm.lead'].create({
            'name': 'Oportunidad asignada F1', 'type': 'opportunity',
            'partner_id': company.id, 'user_id': self.user.id,
        })
        lead.with_user(self.user).write({'name': 'Renombrada F1'})
        lead.with_user(self.user).write({'partner_id': contact.id})
        self.assertEqual(lead.partner_id, contact)
        with self.assertRaises(ValidationError):
            lead.with_user(self.user).write({'partner_id': other_company.id})
        self.assertEqual(lead.partner_id, contact)
        # Pero no puede crearse él mismo una oportunidad de ese cliente.
        with self.assertRaises(ValidationError):
            self.env['crm.lead'].with_user(self.user).create({
                'name': 'Autoasignada F1', 'type': 'opportunity', 'partner_id': company.id,
            })

    def test_opportunities_shared_customers(self):
        other_user = new_test_user(self.env, login='f1_comercial_oport3', groups='base.group_user,sales_team.group_sale_salesman,custom.comerciales')
        other_partner = self.env['res.partner'].create({'name': 'Cliente traspasado oport F1', 'user_id': other_user.id})
        Lead = self.env['crm.lead'].with_user(self.user)
        with self.assertRaises(ValidationError):
            Lead.create({'name': 'Oportunidad traspaso F1', 'type': 'opportunity', 'partner_id': other_partner.id})
        self.user.rms_shared_customer_user_ids = other_user
        lead = Lead.create({'name': 'Oportunidad traspaso F1', 'type': 'opportunity', 'partner_id': other_partner.id})
        self.assertEqual(lead.partner_id, other_partner)

    def test_convert_lead_creates_own_customer(self):
        # Al convertir una iniciativa sin vendedor creando un cliente nuevo,
        # el cliente queda a nombre del comercial y la conversión no falla.
        lead = self.env['crm.lead'].with_user(self.user).create({
            'name': 'Iniciativa F1', 'type': 'lead',
            'contact_name': 'Persona nueva F1', 'partner_name': 'Empresa nueva F1',
        })
        lead.user_id = False
        lead.with_user(self.user)._handle_partner_assignment(create_missing=True)
        self.assertTrue(lead.partner_id)
        self.assertEqual(lead.partner_id.commercial_partner_id.user_id, self.user)
        self.assertTrue(lead.partner_id.with_user(self.user).rms_is_own_customer)

    def test_opportunity_partner_dropdown_only_own_customers(self):
        arch = self.env['crm.lead'].with_user(self.user).get_view(view_type='form')['arch']
        self.assertIn("('rms_is_own_customer', '=', True)", arch)
        quick = self.env.ref('crm.quick_create_opportunity_form', raise_if_not_found=False)
        if quick:
            arch = self.env['crm.lead'].with_user(self.user).get_view(quick.id, 'form')['arch']
            self.assertIn("('rms_is_own_customer', '=', True)", arch)
        arch = self.env['crm.lead'].get_view(view_type='form')['arch']
        self.assertNotIn("('rms_is_own_customer', '=', True)", arch)
        self.user.group_ids |= self.env.ref('rms_ventas_restriccion_comerciales.group_comerciales_all_customers')
        arch = self.env['crm.lead'].with_user(self.user).get_view(view_type='form')['arch']
        self.assertNotIn("('rms_is_own_customer', '=', True)", arch)
