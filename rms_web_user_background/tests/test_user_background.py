import base64

from odoo.exceptions import AccessError
from odoo.tests import HttpCase, tagged
from odoo.tests.common import new_test_user


# Valid 1 x 1 PNG, stored in the same base64 format as fields.Image.
PNG = b'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/AAX+Av4N70a4AAAAAElFTkSuQmCC'


@tagged('post_install', '-at_install')
class TestUserBackground(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(
            cls.env, login='rms_background_user',
            email='rms_background_user@example.com', groups='base.group_user',
        )
        cls.other_user = new_test_user(
            cls.env, login='rms_background_other',
            email='rms_background_other@example.com', groups='base.group_user',
        )

    def test_user_can_write_and_read_own_image(self):
        own_user = self.user.with_user(self.user)
        self.assertFalse(own_user._is_admin())
        own_user.write({'rms_background_image': PNG})
        self.assertEqual(own_user.read(['rms_background_image'])[0]['rms_background_image'], PNG)

    def test_user_cannot_write_another_users_image(self):
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.other_user.with_user(self.user).write({'rms_background_image': PNG})

    def test_session_background_url_and_image_access(self):
        self.user.with_user(self.user).write({'rms_background_image': False})
        self.authenticate(self.user.login, self.user.login)
        info = self.make_jsonrpc_request('/web/session/get_session_info')
        self.assertIs(info['rms_background_url'], False)

        self.user.with_user(self.user).write({'rms_background_image': PNG})
        self.env.flush_all()
        info = self.make_jsonrpc_request('/web/session/get_session_info')
        url = info['rms_background_url']
        self.assertIn(f'/web/image/res.users/{self.user.id}/rms_background_image', url)
        self.assertIn('?unique=', url)
        response = self.url_open(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Content-Type'], 'image/png')
        # The binary route must serve the user's image, rather than its placeholder.
        self.assertEqual(response.content, base64.b64decode(PNG))
