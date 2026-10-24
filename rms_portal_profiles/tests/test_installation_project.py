import base64
from unittest.mock import patch

from odoo.exceptions import UserError
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


@tagged('post_install', '-at_install')
class TestInstallationProjectSendMessage(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(
            cls.env, login='send_project_manager',
            groups='rms_portal_projects.group_installation_project_manager',
        )

    def _project(self, partner):
        return self.env['rms.installation.project'].with_user(self.manager).create({
            'name': 'Proyecto envío', 'partner_id': partner.id,
            'file_name': 'proyecto.html',
            'file_data': base64.b64encode(b'<html>Proyecto</html>'),
        })

    def _send_message(self, project):
        with patch.object(type(self.env['portal.wizard.user']), '_send_email', return_value=True):
            action = project.action_send()
        return self.env[action['res_model']].with_user(self.manager).browse(action['res_id']).message

    def test_manager_sends_to_new_customer(self):
        self.assertFalse(self.manager.has_group('base.group_erp_manager'))
        partner = self.env['res.partner'].create({
            'name': 'Nuevo cliente', 'email': 'send-new@example.com',
            'portal_profile': 'projects',
        })
        project = self._project(partner)
        message = self._send_message(project)
        self.assertEqual(project.state, 'sent')
        self.assertTrue(partner.user_ids.share)
        self.assertTrue(partner.user_ids.has_group('base.group_portal'))
        self.assertTrue(partner.user_ids.has_group('rms_portal_profiles.group_portal_customer'))
        self.assertIn('/web/login?', message)
        self.assertIn('Es tu primer acceso:', message)
        self.assertIn('/my/installation-projects/%s' % project.id, message)

    def test_manager_sends_to_active_customer_without_signup(self):
        user = new_test_user(
            self.env, login='send_active_portal', groups='base.group_portal',
            email='send-active@example.com',
        )
        user.with_user(user).sudo()._update_last_login()
        project = self._project(user.partner_id)
        with patch.object(type(self.env['rms.portal.invite.link']), '_prepare_for_partner') as prepare:
            message = self._send_message(project)
        prepare.assert_not_called()
        self.assertEqual(project.state, 'sent')
        self.assertNotIn('/web/login?', message)
        self.assertNotIn('Es tu primer acceso:', message)
        self.assertIn('/my/installation-projects/%s' % project.id, message)

    def test_internal_customer_stays_draft(self):
        project = self._project(self.manager.partner_id)
        with self.assertRaisesRegex(UserError, 'El cliente es un usuario interno; elige un contacto de cliente.'):
            project.action_send()
        self.assertEqual(project.state, 'draft')

    def test_project_invite_delegates_to_contact(self):
        project = self._project(self.manager.partner_id)
        expected = {'type': 'ir.actions.act_window', 'res_id': 123, 'target': 'new'}
        with patch.object(type(self.env['res.partner']), 'action_open_portal_invite_link', autospec=True, return_value=expected) as action:
            self.assertEqual(project.action_open_portal_invite_link(), expected)
        action.assert_called_once_with(project.partner_id)

    def test_missing_email_stays_draft(self):
        partner = self.env['res.partner'].create({'name': 'Sin correo'})
        project = self._project(partner)
        with self.assertRaisesRegex(UserError, 'no tiene correo electrónico'):
            project.action_send()
        self.assertEqual(project.state, 'draft')
