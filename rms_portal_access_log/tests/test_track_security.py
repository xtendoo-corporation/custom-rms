import json
import re
from unittest.mock import patch

from lxml import html

from odoo.tests import HttpCase, tagged
from odoo.tests.common import new_test_user
from odoo.addons.rms_portal_access_log.controllers import portal


@tagged('post_install', '-at_install')
class TestTrackSecurity(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = new_test_user(
            cls.env, login='track_customer',
            groups='base.group_portal,rms_portal_profiles.group_portal_customer',
        )
        cls.projects = new_test_user(
            cls.env, login='track_projects',
            groups='base.group_portal,rms_portal_profiles.group_portal_projects',
        )
        cls.projects.partner_id.portal_profile = 'projects'
        cls.internal = new_test_user(cls.env, login='track_internal', groups='base.group_user')
        cls.card = cls.env['rms.catalog.card'].create({
            'page_key': 'track-test', 'title': 'Server title', 'brand': 'Server brand',
        })

    def _login(self, user):
        self.authenticate(user.login, user.login)
        if user == self.customer:
            response = self.url_open('/my/catalog')
            self.assertEqual(response.status_code, 200)
            return json.loads(re.search(r'window.RMS_CSRF = (.*?);', response.text)[1])
        response = self.url_open('/my/account')
        self.assertEqual(response.status_code, 200)
        return html.fromstring(response.content).xpath('//input[@name="csrf_token"]/@value')[0]

    def _events(self, user=None):
        return self.env['rms.portal.activity'].sudo().search([
            ('user_id', '=', (user or self.customer).id),
            ('activity_type', 'in', portal.CLIENT_EVENT_TYPES),
        ])

    def _post(self, token=None, **values):
        data = {'kind': 'card', 'key': self.card.page_key,
                'title': 'Forged title', 'brand': 'Forged brand', **values}
        if token is not None:
            data['csrf_token'] = token
        return self.url_open('/my/portal/track', data=data)

    def test_customer_and_server_metadata_and_deduplication(self):
        token = self._login(self.customer)
        self.assertEqual(self._post(token).status_code, 204)
        self.assertEqual(self._post(token, title='Another title', hash='invented').status_code, 204)
        events = self._events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events.page_title, self.card.title)
        self.assertEqual(events.brand, self.card.brand)
        self.assertEqual(events.card_id, self.card)

    def test_missing_csrf(self):
        self._login(self.customer)
        self.assertIn(self._post().status_code, (400, 403))
        self.assertFalse(self._events())

    def test_denied_profiles_and_internal(self):
        for user in (self.projects, self.internal):
            with self.subTest(user=user.login):
                token = self._login(user)
                self.assertEqual(self._post(token).status_code, 204)
                self.assertFalse(self._events(user))

    def test_invalid_events(self):
        token = self._login(self.customer)
        for values in (
            {'kind': 'invented'}, {'key': '../bad<script>'}, {'key': 'missing-card'},
            {'kind': 'search', 'query': 'q' * 101, 'results': '1'},
            {'kind': 'search', 'query': 'q', 'results': '-1'},
            {'kind': 'search', 'query': 'q', 'results': '10001'},
            {'kind': 'search', 'query': 'q', 'results': '1.5'},
            {'kind': 'brand', 'brand': 'Unknown brand'},
        ):
            with self.subTest(values=values):
                self.assertEqual(self._post(token, **values).status_code, 204)
        self.assertFalse(self._events())

    def test_hourly_quota(self):
        token = self._login(self.customer)
        # Start with an empty window: loading the catalog logs catalog_home.
        self.env['rms.portal.activity'].sudo().search([
            ('user_id', '=', self.customer.id),
        ]).unlink()
        with patch.object(portal, 'CLIENT_EVENTS_PER_HOUR', 2):
            for number in range(3):
                self.assertEqual(self._post(
                    token, kind='search', query='query %s' % number, results='1',
                ).status_code, 204)
        self.assertEqual(len(self._events()), 2)
