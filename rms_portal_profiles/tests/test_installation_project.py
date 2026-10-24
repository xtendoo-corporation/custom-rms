from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged('post_install', '-at_install')
class TestInstallationProjectPortalProfile(TransactionCase):
    def test_manager_reads_partner_portal_profile(self):
        manager = new_test_user(
            self.env, login='profile_project_manager',
            groups='rms_portal_projects.group_installation_project_manager',
        )
        self.assertFalse(manager.has_group('base.group_erp_manager'))
        self.assertFalse(manager.has_group('base.group_system'))
        for profile in ('customer', 'marketing', 'projects'):
            with self.subTest(profile=profile):
                partner = self.env['res.partner'].create({
                    'name': 'Profile customer', 'portal_profile': profile,
                })
                project = self.env['rms.installation.project'].create({
                    'name': 'Portal profile', 'partner_id': partner.id,
                })
                self.env.invalidate_all()
                self.assertEqual(partner.with_user(manager).read(['portal_profile'])[0]['portal_profile'], profile)
                self.assertEqual(
                    project.with_user(manager).read(['partner_portal_profile'])[0]['partner_portal_profile'],
                    profile,
                )
