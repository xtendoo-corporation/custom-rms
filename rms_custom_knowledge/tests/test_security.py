import base64
import json
from types import SimpleNamespace
from unittest.mock import patch

from odoo.exceptions import AccessError
from odoo.http import Response
from odoo.tests import HttpCase, TransactionCase, tagged
from odoo.tests.common import new_test_user

from odoo.addons.rms_custom_knowledge.controllers import onlyoffice


def setup_documents(case):
    case.internal = new_test_user(case.env, login='knowledge_internal_s6', groups='base.group_user')
    case.portal = new_test_user(case.env, login='knowledge_portal_s6', groups='base.group_portal', password='portal_s6')
    case.attachment = case.env['ir.attachment'].create({
        'name': 'security-s6.txt',
        'datas': base64.b64encode(b'knowledge private S6'),
        'is_knowledge_document': True,
        'knowledge_category_id': case.env.ref(
            'rms_custom_knowledge.document_knowledge_category_general').id,
    })


@tagged('post_install', '-at_install')
class TestKnowledgeSecurity(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        setup_documents(cls)

    def test_general_access(self):
        self.assertTrue(self.attachment.with_user(self.internal).read(['datas']))
        for user in (self.portal, self.env.ref('base.public_user')):
            with self.assertRaises(AccessError):
                self.attachment.with_user(user).read(['datas'])
        self.assertTrue(self.attachment.sudo().read(['datas']))

    def test_editor_template_escapes_config(self):
        name = '</script><script>alert(1)</script>.docx'
        rendered = self.env['ir.ui.view']._render_template(
            'rms_custom_knowledge.onlyoffice_editor_page', {
                'title': name,
                'server_url': 'https://office.example.test',
                'config_json': json.dumps({'document': {'title': name}}),
            })
        self.assertNotIn('</script><script>alert', str(rendered))
        self.assertIn('data-config=', str(rendered))

    def test_callback_jwt_and_destination(self):
        controller = onlyoffice.OnlyOfficeController()
        params = self.env['ir.config_parameter'].sudo()
        params.set_param('rms_custom_knowledge.onlyoffice_jwt_secret', '')
        fake_request = SimpleNamespace(env=self.env, httprequest=SimpleNamespace(
            headers={}, data=b'{"status":2,"url":"https://evil.example/file"}'))
        fake_request.make_response = lambda body, **kwargs: Response(body, **kwargs)
        with patch.object(onlyoffice, 'request', fake_request), patch.object(
                type(self.env['ir.attachment']), '_verify_onlyoffice_url_token',
                return_value=self.env.uid), patch.object(onlyoffice.requests, 'get') as get:
            self.assertEqual(json.loads(controller.onlyoffice_callback(self.attachment.id, token='signed').get_data())['error'], 1)
            get.assert_not_called()
            params.set_param('rms_custom_knowledge.onlyoffice_jwt_secret', 'test-secret')
            with patch.object(onlyoffice, 'pyjwt', None):
                with self.assertRaises(AccessError):
                    controller._verify_onlyoffice_server_jwt()
            params.set_param('rms_custom_knowledge.onlyoffice_server_url', 'https://office.example.test')
            with patch.object(controller, '_verify_onlyoffice_server_jwt'):
                self.assertEqual(json.loads(controller.onlyoffice_callback(self.attachment.id, token='signed').get_data())['error'], 1)
            get.assert_not_called()

    def test_download_redirect_and_size(self):
        controller = onlyoffice.OnlyOfficeController()
        self.env['ir.config_parameter'].sudo().set_param(
            'rms_custom_knowledge.onlyoffice_server_url', 'https://office.example.test')
        with patch.object(onlyoffice, 'request', SimpleNamespace(env=self.env)), patch.object(
                onlyoffice.requests, 'get') as get:
            response = get.return_value.__enter__.return_value
            response.status_code = 302
            with self.assertRaises(AccessError):
                controller._download_onlyoffice_file('https://office.example.test/file')
            get.assert_called_once_with('https://office.example.test/file', timeout=(10, 30),
                                        stream=True, allow_redirects=False)
            response.status_code = 200
            response.headers = {'Content-Length': str(100 * 1024 * 1024 + 1)}
            with self.assertRaises(AccessError):
                controller._download_onlyoffice_file('https://office.example.test/file')
            response.headers = {}
            response.iter_content.return_value = [b'saved document']
            self.assertEqual(controller._download_onlyoffice_file(
                'https://office.example.test/file'), b'saved document')


@tagged('post_install', '-at_install')
class TestKnowledgeHttpSecurity(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        setup_documents(cls)

    def test_public_cannot_download_content(self):
        response = self.url_open('/web/content/%s' % self.attachment.id)
        self.assertIn(response.status_code, (403, 404))
        self.assertNotIn(b'knowledge private S6', response.content)

    def test_portal_cannot_download(self):
        self.authenticate(self.portal.login, 'portal_s6')
        for url in ('/rms_custom_knowledge/download?ids=%s', '/web/content/%s'):
            response = self.url_open(url % self.attachment.id)
            self.assertIn(response.status_code, (403, 404))
            self.assertNotIn(b'knowledge private S6', response.content)
