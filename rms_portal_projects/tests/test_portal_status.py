from unittest.mock import patch

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged('post_install', '-at_install')
class TestPortalStatus(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(
            cls.env, login='portal_status_manager',
            groups='rms_portal_projects.group_installation_project_manager',
        )

    def _assert_status(self, partner, state, last_login=False):
        project = self.env['rms.installation.project'].create({
            'name': 'Portal status', 'partner_id': partner.id,
        }).with_user(self.manager)
        self.assertFalse(self.manager.has_group('base.group_erp_manager'))
        self.assertFalse(self.manager.has_group('base.group_system'))
        # Simulate a deployment where user reads require elevated privileges.
        users_type = type(self.env['res.users'])
        original_fetch = users_type._fetch_field

        def guarded_fetch(users, field):
            self.assertTrue(users.env.su, 'User fields must be fetched with sudo')
            return original_fetch(users, field)

        self.env.invalidate_all()
        with patch.object(users_type, '_fetch_field', guarded_fetch):
            result = project.read(['portal_access_state', 'portal_last_login'])[0]
        self.assertEqual(result['portal_access_state'], state)
        if last_login:
            self.assertEqual(
                fields.Datetime.to_datetime(result['portal_last_login']).replace(microsecond=0),
                fields.Datetime.to_datetime(last_login).replace(microsecond=0),
            )
        else:
            self.assertFalse(result['portal_last_login'])

    def _user(self, groups='base.group_portal'):
        return new_test_user(self.env, login='portal_status_customer', groups=groups)

    def test_none(self):
        partner = self.env['res.partner'].create({'name': 'No portal'})
        self._assert_status(partner, 'none')

    def test_invited(self):
        user = self._user()
        self._assert_status(user.partner_id, 'invited')

    def test_active(self):
        user = self._user()
        user.with_user(user).sudo()._update_last_login()
        self._assert_status(user.partner_id, 'active', user.login_date)

    def test_archived_portal_has_no_access(self):
        user = self._user()
        user.with_user(user).sudo()._update_last_login()
        user.active = False
        self._assert_status(user.partner_id, 'none')

    def test_internal_including_archived(self):
        user = self._user('base.group_user')
        self._assert_status(user.partner_id, 'internal')
        user.active = False
        self._assert_status(user.partner_id, 'internal')

    def test_internal_takes_precedence(self):
        portal = self._user()
        new_test_user(
            self.env, login='portal_status_internal', groups='base.group_user',
            partner_id=portal.partner_id.id,
        )
        self._assert_status(portal.partner_id, 'internal')
