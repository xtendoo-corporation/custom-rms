import requests

from odoo.tests import HttpCase, tagged
from odoo.tests.common import new_test_user


@tagged('post_install', '-at_install')
class TestCatalogSecurity(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        groups = 'base.group_portal'
        profiles = cls.env['ir.module.module'].search([
            ('name', '=', 'rms_portal_profiles'), ('state', '=', 'installed'),
        ])
        if profiles:
            groups += ',rms_portal_profiles.group_portal_customer'
        cls.customer = new_test_user(
            cls.env, login='catalog_security_customer', groups=groups,
        )

    def test_private_catalog_not_public_static(self):
        response = self.url_open(
            '/rms_portal_catalog/static/catalog/index.html', allow_redirects=False,
        )
        self.assertEqual(response.status_code, 404)

    def test_traversal(self):
        self.authenticate(self.customer.login, self.customer.login)
        for path in (
            '/my/catalog/images/../../__manifest__.py',
            '/my/catalog/images/%2e%2e/%2e%2e/__manifest__.py',
            '/my/catalog/images/../index.html',
            '/my/catalog/images/full/missing.jpg',
        ):
            with self.subTest(path=path):
                response = self.url_open(path, allow_redirects=False)
                self.assertEqual(response.status_code, 404)
                self.assertNotIn(b'RMS Portal Catalog', response.content)
        # Override the prepared URL after requests' dot-segment normalization.
        prepared = self.opener.prepare_request(requests.Request('GET', self.base_url()))
        prepared.url = self.base_url() + '/my/catalog/images/../../__manifest__.py'
        response = self.opener.send(prepared, allow_redirects=False, timeout=10)
        self.assertIn(response.status_code, (400, 404))
        self.assertNotIn(b'RMS Portal Catalog', response.content)

    def test_customer_catalog_and_image(self):
        self.authenticate(self.customer.login, self.customer.login)
        response = self.url_open('/my/catalog/images/reps/salvador-escobar.jpg')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers['Content-Type'].startswith('image/'))
        self.assertEqual(response.headers['Cache-Control'], 'private, max-age=86400')
        self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
        response = self.url_open('/my/catalog')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('static/catalog', response.text)
        self.assertEqual(response.headers['Cache-Control'], 'private, no-store')
