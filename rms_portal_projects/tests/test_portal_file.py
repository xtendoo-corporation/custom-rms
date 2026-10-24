import base64

from odoo.http import content_disposition
from odoo.tests import HttpCase, tagged
from odoo.tests.common import new_test_user

from ..controllers.portal import BACK_TO_PORTAL_BUTTON


@tagged('post_install', '-at_install')
class TestPortalProjectFile(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.owner = new_test_user(
            cls.env, login='portal_project_owner', groups='base.group_portal',
        )
        cls.other = new_test_user(
            cls.env, login='portal_project_other', groups='base.group_portal',
        )
        cls.document = b'<!DOCTYPE html><html><body><p>Project</p></body></html>'
        cls.project = cls.env['rms.installation.project'].create({
            'name': 'Portal file security test',
            'partner_id': cls.owner.partner_id.id,
            'state': 'sent',
            'file_data': base64.b64encode(cls.document),
            'file_name': 'proyecto "cliente".html',
        })

    def _open_file(self):
        return self.url_open(
            '/my/installation-projects/%s/file' % self.project.id,
            allow_redirects=False,
        )

    def test_owner_file_headers_and_button(self):
        self.authenticate(self.owner.login, self.owner.login)
        response = self._open_file()
        self.assertEqual(response.status_code, 200)
        csp = response.headers['Content-Security-Policy']
        self.assertIn('sandbox', csp)
        self.assertNotIn('allow-same-origin', csp)
        self.assertEqual(
            csp,
            'sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox allow-downloads',
        )
        self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(response.headers['Referrer-Policy'], 'no-referrer')
        self.assertEqual(response.headers['Cache-Control'], 'private, no-store')
        self.assertEqual(
            response.headers['Content-Disposition'],
            content_disposition(self.project.file_name, disposition_type='inline'),
        )
        self.assertTrue(response.content.startswith(b'<!DOCTYPE'))
        self.assertEqual(response.content, self.document.replace(
            b'<body>', b'<body>' + BACK_TO_PORTAL_BUTTON, 1,
        ))
        self.assertIn(b'href="/my"', response.content)

    def test_button_insertion_fallbacks(self):
        self.authenticate(self.owner.login, self.owner.login)
        for document, opening in (
            (b'<!DOCTYPE html><HTML><BODY class="project">Content</BODY></HTML>',
             b'<BODY class="project">'),
            (b'<!DOCTYPE html><html><head><title>Project</title></HEAD>Content</html>',
             b'</HEAD>'),
            (b'<p>Project fragment</p>', b''),
        ):
            with self.subTest(document=document):
                self.project.action_reset_to_draft()
                self.project.write({'file_data': base64.b64encode(document), 'state': 'sent'})
                response = self._open_file()
                self.assertEqual(response.status_code, 200)
                offset = document.index(opening) + len(opening) if opening else 0
                self.assertEqual(
                    response.content,
                    document[:offset] + BACK_TO_PORTAL_BUTTON + document[offset:],
                )

    def test_other_portal_user_redirected(self):
        self.authenticate(self.other.login, self.other.login)
        response = self._open_file()
        self.assertEqual(response.status_code, 303)
        self.assertURLEqual(response.headers['Location'], '/my')

    def test_draft_project_redirected(self):
        self.project.state = 'draft'
        self.authenticate(self.owner.login, self.owner.login)
        response = self._open_file()
        self.assertEqual(response.status_code, 303)
        self.assertURLEqual(response.headers['Location'], '/my')

    def test_owner_listing_and_detail(self):
        self.authenticate(self.owner.login, self.owner.login)
        response = self.url_open('/my/installation-projects')
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.project.name, response.text)
        response = self.url_open('/my/installation-projects/%s' % self.project.id)
        self.assertEqual(response.status_code, 200)
        self.assertIn(BACK_TO_PORTAL_BUTTON, response.content)

    def test_owner_detail_without_document(self):
        self.project.action_reset_to_draft()
        self.project.write({'file_data': False, 'state': 'sent'})
        self.authenticate(self.owner.login, self.owner.login)
        response = self.url_open('/my/installation-projects/%s' % self.project.id)
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.project.name, response.text)
