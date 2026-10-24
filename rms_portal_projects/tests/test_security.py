import base64

from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, new_test_user


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
        cls.partner = cls.env['res.partner'].create({'name': 'Security test customer'})
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
