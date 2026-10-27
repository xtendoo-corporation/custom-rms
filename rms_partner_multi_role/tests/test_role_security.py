from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged('post_install', '-at_install')
class TestRoleSecurity(TransactionCase):
    def test_role_permissions(self):
        internal = new_test_user(self.env, login='w2f_role_internal', groups='base.group_user')
        manager = new_test_user(self.env, login='w2f_role_manager', groups='base.group_partner_manager')
        role = self.env['rms.partner.role'].with_user(manager).create({'name': 'Rol W2F', 'code': 'w2f'})
        self.assertTrue(role.with_user(internal).read(['name']))
        with self.assertRaises(AccessError):
            role.with_user(internal).write({'name': 'Cambio'})
        with self.assertRaises(AccessError):
            role.with_user(internal).create({'name': 'Otro', 'code': 'otro'})
        with self.assertRaises(AccessError):
            role.with_user(internal).unlink()
        role.write({'name': 'Cambio autorizado'})
        role.unlink()
