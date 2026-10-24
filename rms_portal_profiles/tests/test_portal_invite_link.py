from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged('post_install', '-at_install')
class TestPortalInviteLink(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(
            cls.env, login='invite_project_manager',
            groups='rms_portal_projects.group_installation_project_manager',
        )
        cls.admin = new_test_user(
            cls.env, login='invite_admin', groups='base.group_erp_manager,base.group_partner_manager',
        )
        cls.employee = new_test_user(
            cls.env, login='invite_employee', groups='base.group_user',
            email='invite-employee@example.com',
        )

    def _partner(self, **values):
        return self.env['res.partner'].create({
            'name': 'Invite customer', 'email': 'invite-customer@example.com', **values,
        })

    def _portal_user(self):
        return new_test_user(
            self.env, login='invite_existing_portal', groups='base.group_portal',
            email='invite-existing@example.com',
        )

    def _invite(self, partner, actor=None):
        # Exercise the public button, including transient ACLs. Prevent actual mail.
        with patch.object(type(self.env['portal.wizard.user']), '_send_email', return_value=True):
            action = partner.with_user(actor or self.manager).action_open_portal_invite_link()
        return self.env['rms.portal.invite.link'].with_user(actor or self.manager).browse(action['res_id'])

    def _assert_audit(self, partner, actor, link_type):
        messages = partner.message_ids.filtered(
            lambda message: 'generó un enlace de portal de tipo:' in str(message.body)
        )
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages.author_id, actor.partner_id)
        self.assertIn(actor.name, str(messages.body))
        self.assertIn(link_type, str(messages.body))
        self.assertNotIn('/web/login?', str(messages.body))

    def test_manager_invites_new_customer(self):
        self.assertFalse(self.manager.has_group('base.group_erp_manager'))
        partner = self._partner(portal_profile='projects')
        wizard = self._invite(partner)
        user = partner.user_ids
        self.assertEqual(len(user), 1)
        self.assertTrue(user.share)
        self.assertTrue(user.has_group('base.group_portal'))
        self.assertTrue(user.has_group('rms_portal_profiles.group_portal_customer'))
        self.assertFalse(user.has_group('base.group_user'))
        self.assertEqual(partner.portal_profile, 'customer')
        self.assertEqual(wizard.link_type, 'signup')
        self.assertIn('/web/login?', wizard.url)
        self._assert_audit(partner, self.manager, 'registro')

    def test_manager_regenerates_unused_portal_signup(self):
        user = self._portal_user()
        self.assertFalse(user.login_date)
        self.assertFalse(user.log_ids)
        wizard = self._invite(user.partner_id)
        self.assertEqual(wizard.link_type, 'signup')
        self.assertEqual(user.partner_id.user_ids, user)
        self._assert_audit(user.partner_id, self.manager, 'registro')

    def test_manager_cannot_reset_used_portal(self):
        user = self._portal_user()
        user.with_user(user).sudo()._update_last_login()
        self.assertTrue(user.log_ids)
        self.assertTrue(user.login_date)
        with self.assertRaisesRegex(UserError, 'Este contacto ya usa el portal; para restablecer su contraseña pídeselo a un administrador.'):
            self._invite(user.partner_id)
        self.assertFalse(user.partner_id.message_ids.filtered(
            lambda message: 'generó un enlace' in str(message.body)
        ))

    def test_manager_cannot_reset_archived_used_portal(self):
        user = self._portal_user()
        user.with_user(user).sudo()._update_last_login()
        user.active = False
        with self.assertRaisesRegex(UserError, 'Este contacto ya usa el portal'):
            self._invite(user.partner_id)
        self.assertFalse(user.active)

    def test_manager_cannot_invite_internal_user(self):
        before = self.employee.group_ids
        for active in (True, False):
            self.employee.active = active
            with self.assertRaisesRegex(UserError, 'usuario interno'):
                self._invite(self.employee.partner_id)
            self.assertEqual(self.employee.group_ids, before)
            self.assertEqual(self.employee.active, active)

    def test_manager_cannot_change_profile(self):
        partner = self._partner()
        with self.assertRaisesRegex(AccessError, 'Solo un administrador puede cambiar el perfil de portal.'):
            partner.with_user(self.manager).write({'portal_profile': 'projects'})
        self.assertEqual(partner.portal_profile, 'customer')

    def test_admin_changes_profile_and_syncs_groups(self):
        user = self._portal_user()
        user.partner_id.with_user(self.admin).write({'portal_profile': 'projects'})
        self.assertTrue(user.has_group('rms_portal_profiles.group_portal_projects'))
        self.assertFalse(user.has_group('rms_portal_profiles.group_portal_customer'))
        self.assertTrue(user.share)
        self.assertTrue(user.has_group('base.group_portal'))
        user.partner_id.with_user(self.admin).write({'portal_profile': 'customer'})
        self.assertTrue(user.has_group('rms_portal_profiles.group_portal_customer'))
        self.assertFalse(user.has_group('rms_portal_profiles.group_portal_projects'))

    def test_admin_reset_is_audited(self):
        user = self._portal_user()
        user.with_user(user).sudo()._update_last_login()
        wizard = self._invite(user.partner_id, self.admin)
        self.assertEqual(wizard.link_type, 'reset')
        self._assert_audit(user.partner_id, self.admin, 'restablecer contraseña')

    def test_admin_signup_preserves_profile_and_is_audited(self):
        partner = self._partner(portal_profile='marketing')
        wizard = self._invite(partner, self.admin)
        self.assertEqual(wizard.link_type, 'signup')
        self.assertEqual(partner.portal_profile, 'marketing')
        self.assertTrue(partner.user_ids.has_group('rms_portal_profiles.group_portal_marketing'))
        self._assert_audit(partner, self.admin, 'registro')

    def test_missing_email(self):
        with self.assertRaisesRegex(UserError, 'no tiene correo electrónico'):
            self._invite(self._partner(email=False))

    def test_employee_cannot_generate_link(self):
        with self.assertRaises(AccessError):
            self._invite(self._partner(), self.employee)
