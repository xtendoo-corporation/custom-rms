import json
import re

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

        cls.catalog_product = cls.env['product.product'].create({
            'name': 'Catalog security allowed', 'sale_ok': True,
            'company_id': cls.customer.company_id.id,
        })
        cls.other_product = cls.env['product.product'].create({
            'name': 'Catalog security outside', 'sale_ok': True,
        })
        cls.card = cls.env['rms.catalog.card'].create({
            'page_key': 'security-test',
            'line_ids': [(0, 0, {'product_id': cls.catalog_product.id})],
        })

    def _login_catalog(self):
        self.authenticate(self.customer.login, self.customer.login)
        response = self.url_open('/my/catalog')
        self.assertEqual(response.status_code, 200)
        return json.loads(re.search(r'window.RMS_CSRF = (.*?);', response.text)[1])

    def _cart(self):
        response = self.url_open('/my/catalog/quote')
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_quote_allowed_and_outside_catalog(self):
        token = self._login_catalog()
        response = self.url_open('/my/catalog/quote/add', data={
            'product_id': self.catalog_product.product_tmpl_id.id, 'csrf_token': token,
        })
        self.assertEqual(response.status_code, 200)
        cart = response.json()
        self.assertEqual(cart['count'], 1)
        self.assertEqual(cart['lines'][0]['product_id'], self.catalog_product.product_tmpl_id.id)
        for action in ('add', 'decrease', 'remove'):
            with self.subTest(action=action):
                response = self.url_open('/my/catalog/quote/' + action, data={
                    'product_id': self.other_product.product_tmpl_id.id, 'csrf_token': token,
                })
                self.assertEqual(response.status_code, 404)
                self.assertEqual(self._cart(), cart)

    def test_quote_requires_csrf(self):
        self._login_catalog()
        before = self._cart()
        for action in ('add', 'decrease', 'remove'):
            with self.subTest(action=action):
                response = self.url_open('/my/catalog/quote/' + action, data={
                    'product_id': self.catalog_product.product_tmpl_id.id,
                })
                self.assertIn(response.status_code, (400, 403))
                self.assertEqual(self._cart(), before)

    def test_product_image_outside_catalog(self):
        self._login_catalog()
        # A real image ensures the 404 tests membership rather than missing data.
        self.other_product.product_tmpl_id.image_1920 = (
            'iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEElEQVR4nGP4z8AARAwQCgAf7gP9i18U1AAAAABJRU5ErkJggg=='
        )
        response = self.url_open('/my/catalog/product-image/%d' % self.other_product.product_tmpl_id.id)
        self.assertEqual(response.status_code, 404)

    def test_prices_only_active_card_products(self):
        self._login_catalog()
        response = self.url_open('/my/catalog/prices/security-test')
        self.assertEqual(response.status_code, 200)
        self.assertEqual([p['id'] for p in response.json()['products']],
                         [self.catalog_product.product_tmpl_id.id])
        self.card.active = False
        response = self.url_open('/my/catalog/prices/security-test')
        self.assertEqual(response.json()['products'], [])

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
