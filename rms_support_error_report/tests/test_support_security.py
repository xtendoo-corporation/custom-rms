from unittest.mock import patch

from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged('post_install', '-at_install')
class TestSupportSecurity(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.reporter = new_test_user(cls.env, login='w2g_support', groups='base.group_user')
        cls.Ticket = cls.env['rms.support.ticket']

    def test_server_action_requires_reporter_access(self):
        action = self.env['ir.actions.server'].sudo().create({
            'name': 'Acción privada',
            'model_id': self.env['ir.model']._get_id('res.partner'),
            'state': 'code', 'code': 'private_marker = True',
        })
        ticket = self.Ticket.create({
            'user_id': self.reporter.id,
            'traceback': 'File "ir.actions.server(%s,)", line 1, in test' % action.id,
        })
        original = type(action).check_access

        def restricted(records, operation):
            # Simula una regla que solo impide leer al reportante.
            if records.env.uid == self.reporter.id and action.id in records.ids:
                raise AccessError('Acción privada')
            return original(records, operation)

        with patch.object(type(action), 'check_access', restricted):
            self.assertEqual(ticket.sudo()._server_action_code_parts(), [])

    def test_url_and_diagnostic_redacted(self):
        result = self.Ticket.with_user(self.reporter).report_error({
            'error_message': 'password=secret sk-examplekey AIzaExamplekey',
            'traceback': 'Authorization: Bearer private\ntoken=private',
            'url': 'https://example.com/odoo?model=res.partner&access_token=secret#id=3&token=secret',
        })
        ticket = self.Ticket.search([('name', '=', result['name'])])
        self.assertEqual(ticket.url, 'https://example.com/odoo?model=res.partner#id=3')
        for secret in ('secret', 'sk-examplekey', 'AIzaExamplekey', 'private'):
            self.assertNotIn(secret, ticket.error_message + ticket.traceback)
        # También se sanea el histórico antes de enviarlo al proveedor.
        ticket.url = 'https://example.com/?access_token=legacy'
        ticket.error_message = 'password=legacy'
        with patch.object(type(ticket), '_safe_code_context', return_value=''), \
                patch.object(type(ticket), '_installed_custom_modules_text', return_value=''):
            self.assertNotIn('legacy', ticket._build_user_prompt())

    def test_duplicate_reports_are_rate_limited(self):
        from odoo.addons.rms_support_error_report.models import support_ticket

        reporter = self.Ticket.with_user(self.reporter)
        with patch.object(support_ticket, 'MAX_REPORTS_PER_USER_HOUR', 2):
            first = reporter.report_error({'error_message': 'Duplicado W2G'})
            self.assertEqual(first['status'], 'created')
            self.assertEqual(reporter.report_error({'error_message': 'Duplicado W2G'})['status'], 'duplicate')
            ticket = self.Ticket.search([('name', '=', first['name'])])
            message_count = len(ticket.message_ids)
            self.assertEqual(reporter.report_error({'error_message': 'Duplicado W2G'})['status'], 'rate_limited')
            self.assertEqual(ticket.occurrence_count, 2)
            self.assertEqual(len(ticket.message_ids), message_count)

    def test_notification_failure_keeps_analysis(self):
        ticket = self.Ticket.create({'user_id': self.reporter.id})
        report = {
            'classification': 'bug', 'severity': 'low', 'module': '',
            'summary': 'Analizada', 'what_fails': '', 'why_fails': '',
            'solutions': [], 'user_advice': '', 'confidence': 'high',
        }
        with patch.object(type(ticket), '_run_ai_analysis', return_value=report), \
                patch.object(type(ticket), '_notify_support_channel', side_effect=RuntimeError('Canal')):
            ticket._analyze_and_notify()
        self.assertEqual(ticket.state, 'analyzed')

    def test_secret_source_file_is_omitted(self):
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, 'credentials.py')
            with open(path, 'w') as source:
                source.write('secret = True')
            with patch.object(type(self.Ticket), '_allowed_source_roots', return_value=[root]):
                self.assertFalse(self.Ticket._safe_source_path(path))
