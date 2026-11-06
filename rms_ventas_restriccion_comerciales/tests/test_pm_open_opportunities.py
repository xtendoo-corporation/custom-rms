from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user

from odoo.addons.rms_ventas_restriccion_comerciales.pm_access import (
    drop_pm_see_all, mark_pm_closing_stages, remove_or_term,
)

# Dominio real de «CUSTOM/Contactos propios» en producción (06/11/2026).
PROD_OWN_CONTACTS_DOMAIN = (
    "['|', '|', '|', '|', '|', '|', ('user_id', '=', user.id), ('user_ids', '!=', False), "
    "(user.has_group('base.group_system'), '=', True), "
    "(user.has_group('sales_team.group_sale_manager'), '=', True), "
    "(user.has_group('custom.departamento_logistica'), '=', True), "
    "(user.has_group('custom.departamento_administracion'), '=', True), "
    "(user.has_group('custom.product_managers'), '=', True)]"
)


@tagged('post_install', '-at_install')
class TestProductManagerOpenOpportunities(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for name in ('comerciales', 'product_managers'):
            if not cls.env.ref('custom.%s' % name, raise_if_not_found=False):
                group = cls.env['res.groups'].create({'name': 'Prueba PM %s' % name})
                cls.env['ir.model.data'].create({
                    'module': 'custom', 'name': name, 'model': 'res.groups', 'res_id': group.id,
                })
        # Como «CUSTOM/Contactos propios» en producción, ya sin la excepción de
        # Product Managers: solo sus contactos y los de los usuarios.
        cls.env['ir.rule'].create({
            'name': 'Contactos propios (prueba PM)',
            'model_id': cls.env.ref('base.model_res_partner').id,
            'groups': [(6, 0, (cls.env.ref('custom.comerciales') | cls.env.ref('custom.product_managers')).ids)],
            'domain_force': "['|', ('user_id', '=', user.id), ('user_ids', '!=', False)]",
            'perm_read': True, 'perm_write': True, 'perm_create': True, 'perm_unlink': False,
        })
        comercial = 'base.group_user,sales_team.group_sale_salesman,custom.comerciales'
        cls.salvador = new_test_user(cls.env, login='pm_salvador', groups=comercial)
        # Alex es comercial y Product Manager; ve los presupuestos de sus
        # categorías (en producción, por la regla «Presupuestos Product Managers»).
        cls.alex = new_test_user(
            cls.env, login='pm_alex',
            groups=comercial + ',custom.product_managers,sales_team.group_sale_salesman_all_leads',
        )
        cls.manu = new_test_user(
            cls.env, login='pm_manu', groups='base.group_user,sales_team.group_sale_salesman,custom.product_managers',
        )
        cls.otro = new_test_user(cls.env, login='pm_otro_comercial', groups=comercial)
        cls.categ = cls.env['product.category'].create({
            'name': 'Categoría PM', 'product_manager_ids': [(6, 0, (cls.alex | cls.manu).ids)],
        })
        cls.subcateg = cls.env['product.category'].create({'name': 'Subcategoría PM', 'parent_id': cls.categ.id})
        cls.other_categ = cls.env['product.category'].create({'name': 'Otra categoría'})
        cls.product = cls.env['product.product'].create({'name': 'Producto PM', 'categ_id': cls.subcateg.id})
        cls.other_product = cls.env['product.product'].create({'name': 'Producto ajeno', 'categ_id': cls.other_categ.id})
        cls.agt = cls.env['res.partner'].create({'name': 'AGT', 'is_company': True, 'user_id': cls.salvador.id})
        cls.agt_contact = cls.env['res.partner'].create({'name': 'Contacto AGT', 'parent_id': cls.agt.id})
        cls.other_customer = cls.env['res.partner'].create({'name': 'Otro cliente de Salvador', 'user_id': cls.salvador.id})
        cls.stage_open = cls.env['crm.stage'].create({'name': 'Pres Enviado PM'})
        cls.stage_closed = cls.env['crm.stage'].create({'name': 'Entregados PM', 'rms_closes_pm_access': True})
        cls.lead = cls.env['crm.lead'].create({
            'name': 'Oportunidad AGT', 'type': 'opportunity', 'partner_id': cls.agt.id,
            'user_id': cls.salvador.id, 'stage_id': cls.stage_open.id,
        })
        cls.order = cls.env['sale.order'].create({
            'partner_id': cls.agt.id, 'user_id': cls.salvador.id, 'opportunity_id': cls.lead.id,
            'order_line': [(0, 0, {'product_id': cls.product.id})],
        })

    def _visible(self, user, partners=None):
        partners = partners if partners is not None else (self.agt | self.agt_contact)
        self.env.invalidate_all()
        return self.env['res.partner'].with_user(user).search([('id', 'in', partners.ids)])

    def test_pm_sees_customer_of_open_opportunity(self):
        self.assertEqual(self._visible(self.alex), self.agt | self.agt_contact)
        self.assertEqual(self.agt.with_user(self.alex).name, 'AGT')
        self.assertEqual(self._visible(self.manu), self.agt | self.agt_contact)
        # Solo lectura, y no pasa a ser cliente suyo.
        with self.assertRaises(AccessError):
            self.agt.with_user(self.alex).write({'name': 'Cambiado'})
        self.assertFalse(self.agt.with_user(self.alex).rms_is_own_customer)
        with self.assertRaises(ValidationError):
            self.env['crm.lead'].with_user(self.alex).create({
                'name': 'Autoasignada', 'type': 'opportunity', 'partner_id': self.agt.id,
            })
        # Los demás clientes de Salvador siguen ocultos, y un comercial que no
        # es Product Manager no ve AGT.
        self.assertFalse(self._visible(self.alex, self.other_customer))
        self.assertFalse(self._visible(self.otro))

    def test_access_ends_when_opportunity_closes(self):
        self.lead.stage_id = self.stage_closed
        self.assertFalse(self._visible(self.alex))
        self.assertFalse(self._visible(self.manu))
        self.lead.stage_id = self.stage_open
        self.assertTrue(self._visible(self.alex))
        self.lead.action_archive()
        self.assertFalse(self._visible(self.alex))

    def test_needs_product_of_own_category_in_active_quotation(self):
        self.order.order_line.product_id = self.other_product
        self.assertFalse(self._visible(self.alex))
        self.order.order_line.product_id = self.product
        self.assertTrue(self._visible(self.alex))
        self.order.state = 'cancel'
        self.assertFalse(self._visible(self.alex))

    def test_chatter_works_after_losing_access(self):
        self.order.message_subscribe(partner_ids=self.agt.ids)
        self.lead.stage_id = self.stage_closed
        self.assertFalse(self._visible(self.alex))
        for record in (self.order, self.lead):
            self.env.invalidate_all()
            suggested = record.with_user(self.alex)._message_get_suggested_recipients(
                reply_discussion=True, no_create=True,
            )
            self.assertNotIn(self.agt.id, {r['partner_id'] for r in suggested})

    def test_mark_closing_stages(self):
        names = ['Entregados 🤩', 'Perdido ❌', 'Eliminados', 'Ganado 🤝', 'en Pedidos 📦']
        stages = self.env['crm.stage'].browse()
        for name in names:
            stages |= self.env['crm.stage'].create({'name': name})
        mark_pm_closing_stages(self.env)
        self.assertEqual(stages.filtered('rms_closes_pm_access').mapped('name'), names[:3])

    def test_remove_pm_from_own_contacts_rule(self):
        new = remove_or_term(PROD_OWN_CONTACTS_DOMAIN, 'custom.product_managers')
        self.assertEqual(new, (
            "['|', '|', '|', '|', '|', ('user_id', '=', user.id), ('user_ids', '!=', False), "
            "(user.has_group('base.group_system'), '=', True), "
            "(user.has_group('sales_team.group_sale_manager'), '=', True), "
            "(user.has_group('custom.departamento_logistica'), '=', True), "
            "(user.has_group('custom.departamento_administracion'), '=', True)]"
        ))
        self.assertIsNone(remove_or_term(new, 'custom.product_managers'))
        self.assertIsNone(remove_or_term("[('a', '=', 1), ('b', '=', 2)]", 'b'))
        rule = self.env['ir.rule'].create({
            'name': 'CUSTOM/Contactos propios',
            'model_id': self.env.ref('base.model_res_partner').id,
            'groups': [(6, 0, self.env.ref('custom.comerciales').ids)],
            'domain_force': "['|', '|', ('user_id', '=', user.id), "
                            "(user.has_group('base.group_system'), '=', True), "
                            "(user.has_group('custom.product_managers'), '=', True)]",
        })
        drop_pm_see_all(self.env)
        self.assertEqual(rule.domain_force, "['|', ('user_id', '=', user.id), "
                                            "(user.has_group('base.group_system'), '=', True)]")
