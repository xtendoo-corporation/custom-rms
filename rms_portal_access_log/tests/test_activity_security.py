from datetime import timedelta

from lxml import etree

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged("post_install", "-at_install")
class TestActivitySecurity(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = new_test_user(cls.env, login='activity_employee', groups='rms_portal_access_log.group_portal_weekly_report')
        cls.project = cls.env['rms.installation.project'].create({
            'name': 'Project name visible in activity',
            'partner_id': cls.employee.partner_id.id,
        })
        cls.activity = cls.env['rms.portal.activity'].sudo().create({
            'activity_type': 'project', 'project_id': cls.project.id,
            'name': cls.project.name, 'partner_id': cls.employee.partner_id.id,
        })

    def test_employee_reads_activity_view_fields_without_project_access(self):
        self.assertFalse(self.employee.has_group(
            'rms_portal_projects.group_installation_project_manager'
        ))
        Activity = self.env['rms.portal.activity'].with_user(self.employee)
        for view_type in ('list', 'form', 'search', 'pivot'):
            with self.subTest(view_type=view_type):
                arch = etree.fromstring(Activity.get_view(view_type=view_type)['arch'])
                self.assertFalse(arch.xpath("//field[@name='project_id']"))
                self.assertFalse(arch.xpath("//filter[contains(@context, 'project_id')]"))
                if view_type in ('list', 'form'):
                    names = list(dict.fromkeys(arch.xpath('//field/@name')))
                    self.assertIn('name', names)
                    row = self.activity.with_user(self.employee).read(names)[0]
                    self.assertEqual(row['name'], self.project.name)
        action = self.employee.partner_id.with_user(self.employee).action_open_portal_interest()
        self.assertEqual(action['res_model'], 'rms.portal.activity')

    def test_employee_can_prepare_weekly_report(self):
        now = fields.Datetime.now()
        values = self.env['rms.portal.weekly.report'].with_user(self.employee)._prepare_report_values(
            now - timedelta(days=1), now + timedelta(seconds=1),
        )
        self.assertTrue(values['clients'])
