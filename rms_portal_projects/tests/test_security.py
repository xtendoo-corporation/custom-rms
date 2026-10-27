import base64

from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged('post_install', '-at_install')
class TestInstallationProjectSecurity(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = new_test_user(cls.env, login='project_employee', groups='base.group_user')
        cls.manager = new_test_user(
            cls.env, login='project_manager',
            groups='rms_portal_projects.group_installation_project_manager',
        )
        cls.admin = new_test_user(cls.env, login='project_admin', groups='base.group_system')
        cls.responsibility_admin = new_test_user(
            cls.env, login='project_responsibility_admin',
            groups='base.group_erp_manager,rms_portal_projects.group_installation_project_manager',
        )
        cls.partner = cls.env['res.partner'].create({
            'name': 'Security test customer', 'email': 'security.customer@example.com',
        })
        cls.values = {
            'name': 'Security test project', 'partner_id': cls.partner.id,
            'file_name': 'project.html',
            'file_data': base64.b64encode(b'<html>Project</html>'),
        }

    def test_employee_cannot_read_or_create(self):
        self.assertFalse(self.employee.has_group(
            'rms_portal_projects.group_installation_project_manager'
        ))
        project = self.env['rms.installation.project'].create(self.values)
        with self.assertRaises(AccessError):
            project.with_user(self.employee).read(['name'])
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.env['rms.installation.project'].with_user(self.employee).create(self.values)

    def test_manager_can_create_read_and_send(self):
        project = self.env['rms.installation.project'].with_user(self.manager).create(self.values)
        self.assertEqual(project.read(['name'])[0]['name'], self.values['name'])
        project.action_send()
        self.assertEqual(project.state, 'sent')

    def test_system_group_implies_manager(self):
        group = self.env.ref('rms_portal_projects.group_installation_project_manager')
        self.assertIn(group, self.env.ref('base.group_system').implied_ids)
        self.assertTrue(self.admin.has_group(group.get_external_id()[group.id]))

    def test_manager_create_forces_own_responsibility(self):
        projects = self.env['rms.installation.project'].with_user(self.manager).create([
            {**self.values, 'user_id': self.employee.id},
            {**self.values, 'user_id': False},
            dict(self.values),
        ])
        for project in projects:
            self.assertEqual(project.user_id, self.manager)

    def test_manager_cannot_change_responsibility(self):
        project = self.env['rms.installation.project'].with_user(self.manager).create(self.values)
        project.write({'user_id': self.manager.id})
        for user_id in (self.employee.id, False):
            with self.assertRaisesRegex(
                AccessError, 'Solo un administrador puede cambiar el responsable del proyecto[.]',
            ), self.cr.savepoint():
                project.write({'user_id': user_id})
        self.assertEqual(project.user_id, self.manager)

    def test_admin_can_choose_and_change_responsibility(self):
        project = self.env['rms.installation.project'].with_user(
            self.responsibility_admin,
        ).create({**self.values, 'user_id': self.employee.id})
        self.assertEqual(project.user_id, self.employee)
        project.write({'user_id': self.manager.id})
        self.assertEqual(project.user_id, self.manager)

    def test_manager_cannot_change_responsibility_on_recordset(self):
        own_project = self.env['rms.installation.project'].with_user(self.manager).create(self.values)
        other_project = self.env['rms.installation.project'].with_user(
            self.responsibility_admin,
        ).create({**self.values, 'user_id': self.employee.id})
        projects = (own_project | other_project).with_user(self.manager)
        with self.assertRaises(AccessError), self.cr.savepoint():
            projects.write({'user_id': self.manager.id})
        self.assertEqual(other_project.user_id, self.employee)

    def test_manager_company_rule(self):
        other_company = self.env['res.company'].create({'name': 'Other project company'})
        project = self.env['rms.installation.project'].create({
            **self.values, 'company_id': other_company.id,
        })
        with self.assertRaises(AccessError):
            project.with_user(self.manager).with_context(
                allowed_company_ids=[self.env.company.id],
            ).read(['name'])
        shared = self.env['rms.installation.project'].with_user(self.manager).create({
            **self.values, 'company_id': False,
        })
        self.assertEqual(shared.read(['name'])[0]['name'], self.values['name'])

    def test_portal_search_across_companies(self):
        company_a = self.env.company
        company_b = self.env['res.company'].create({'name': 'Portal project company B'})
        portal = new_test_user(
            self.env, login='project_portal_cross_company', groups='base.group_portal',
            company_id=company_a.id, company_ids=[(6, 0, company_a.ids)],
        )
        project = self.env['rms.installation.project'].create({
            **self.values, 'partner_id': portal.partner_id.id,
            'company_id': company_b.id, 'state': 'sent',
        })
        draft = self.env['rms.installation.project'].create({
            **self.values, 'partner_id': portal.partner_id.id, 'company_id': company_b.id,
        })
        other_customer = self.env['rms.installation.project'].create({
            **self.values, 'company_id': company_b.id, 'state': 'sent',
        })
        visible = self.env['rms.installation.project'].with_user(portal).with_context(
            allowed_company_ids=company_a.ids,
        ).search([('id', 'in', (project | draft | other_customer).ids)])
        self.assertEqual(visible.ids, project.ids)

    def test_manager_and_admin_company_search(self):
        company_a = self.env.company
        company_b = self.env['res.company'].create({'name': 'Manager project company B'})
        self.manager.write({'company_id': company_a.id, 'company_ids': [(6, 0, company_a.ids)]})
        self.admin.write({
            'company_id': company_a.id,
            'company_ids': [(6, 0, (company_a | company_b).ids)],
        })
        project_a = self.env['rms.installation.project'].create({
            **self.values, 'company_id': company_a.id,
        })
        project_b = self.env['rms.installation.project'].create({
            **self.values, 'company_id': company_b.id,
        })
        domain = [('id', 'in', (project_a | project_b).ids)]
        manager_projects = self.env['rms.installation.project'].with_user(
            self.manager,
        ).with_context(allowed_company_ids=company_a.ids).search(domain)
        self.assertEqual(manager_projects.ids, project_a.ids)
        admin_projects = self.env['rms.installation.project'].with_user(
            self.admin,
        ).with_context(allowed_company_ids=(company_a | company_b).ids).search(domain)
        self.assertEqual(set(admin_projects.ids), {project_a.id, project_b.id})

    def test_portal_cannot_read_internal_project_fields(self):
        portal = new_test_user(
            self.env, login='project_field_portal', groups='base.group_portal',
        )
        project = self.env['rms.installation.project'].create({
            **self.values, 'partner_id': portal.partner_id.id,
            'state': 'sent', 'description': 'Private installation notes',
        })
        public_fields = ['name', 'state', 'date', 'file_name']
        self.assertEqual(
            project.with_user(portal).read(public_fields)[0],
            project.read(public_fields)[0],
        )
        for field in (
            'description', 'user_id', 'portal_access_state',
            'portal_last_login', 'file_data', 'company_id',
        ):
            with self.subTest(field=field):
                with self.assertRaises(AccessError):
                    project.with_user(portal).read([field])
                project.with_user(self.manager).read([field])

    def test_partner_multi_role_internal_fields(self):
        if 'technical_notes' not in self.env['res.partner']._fields:
            self.skipTest('Install rms_partner_multi_role to test partner field security')
        portal = new_test_user(
            self.env, login='partner_notes_portal', groups='base.group_portal',
        )
        partner = portal.partner_id
        partner.technical_notes = 'Private technical notes'
        fields = [
            'technical_notes', 'general_notes', 'role_pricelist_notes',
            'custom_invoice_address', 'custom_delivery_address', 'rms_role_ids',
            'is_role_invoice', 'is_role_delivery', 'is_role_pricelist',
            'is_role_technical', 'is_role_general',
        ]
        self.assertEqual(partner.with_user(portal).read(['name'])[0]['name'], partner.name)
        for field in fields:
            with self.subTest(field=field):
                with self.assertRaises(AccessError):
                    partner.with_user(portal).read([field])
                partner.with_user(self.employee).read([field])
        self.assertEqual(
            partner.with_user(self.employee).read(['technical_notes'])[0]['technical_notes'],
            'Private technical notes',
        )

    def test_partner_address_resolution_with_internal_roles(self):
        if 'rms_role_ids' not in self.env['res.partner']._fields:
            self.skipTest('Install rms_partner_multi_role to test address resolution')
        portal = new_test_user(
            self.env, login='partner_address_portal', groups='base.group_portal',
        )
        role = self.env['rms.partner.role'].create({'name': 'Invoice test', 'code': 'invoice'})
        child = self.env['res.partner'].create({
            'name': 'Invoice contact', 'parent_id': portal.partner_id.id,
            'rms_role_ids': [(6, 0, role.ids)],
        })
        self.assertEqual(
            portal.partner_id.with_user(portal).address_get(['invoice'])['invoice'], child.id,
        )

    def test_portal_chatter_access_characterization(self):
        portal = new_test_user(
            self.env, login='project_chatter_portal', groups='base.group_portal',
        )
        project = self.env['rms.installation.project'].create({
            **self.values, 'partner_id': portal.partner_id.id, 'state': 'sent',
        })
        project.message_subscribe(partner_ids=portal.partner_id.ids)
        note = project.message_post(body='Internal note', message_type='comment', subtype_xmlid='mail.mt_note')
        comment = project.message_post(body='Customer message', subtype_xmlid='mail.mt_comment')
        with self.assertRaises(AccessError):
            note.with_user(portal).read(['body'])
        self.assertIn('Customer message', comment.with_user(portal).read(['body'])[0]['body'])
        with self.assertRaises(AccessError):
            project.with_user(portal).read(['message_follower_ids'])

    def test_product_manager_fields_are_internal(self):
        if (
            'product.template' not in self.env.registry.models
            or 'category_product_manager_ids' not in self.env['product.template']._fields
        ):
            self.skipTest('Install rms_sale_category_product_manager for this check')
        portal = new_test_user(
            self.env, login='product_manager_field_portal', groups='base.group_portal',
        )
        product = self.env['product.template'].create({'name': 'Internal manager test'})
        with self.assertRaises(AccessError):
            product.with_user(portal).read(['category_product_manager_ids'])
        product.with_user(self.employee).read(['category_product_manager_ids'])
