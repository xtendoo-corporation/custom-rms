from unittest.mock import patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged('post_install', '-at_install')
class TestSupportEmail(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.reporter = new_test_user(
            cls.env, login='support_email_reporter', groups='base.group_user',
            email='reporter@rmsproaudio.com',
        )
        cls.Ticket = cls.env['rms.support.ticket'].sudo()
        cls.Mail = cls.env['mail.mail'].sudo()
        cls.report = {
            'classification': 'bug', 'severity': 'high', 'confidence': 'high',
            'module': 'rms_support_error_report', 'summary': 'Diagnóstico de prueba',
            'what_fails': 'Fallo de prueba', 'why_fails': 'Causa de prueba',
            'solutions': [], 'user_advice': '',
        }

    def setUp(self):
        super().setUp()
        self.env['ir.config_parameter'].sudo().set_param(
            'rms_support_error_report.notify_email',
            'a@rmsproaudio.com, b@rmsproaudio.com',
        )
        self.ticket = self.Ticket.create({
            'name': 'INC-EMAIL-TEST', 'user_id': self.reporter.id,
            'error_type': 'ValueError', 'error_message': 'Mensaje <privado>',
        })

    def _ticket_mails(self):
        return self.Mail.search([('subject', 'ilike', self.ticket.name)])

    def _analyze(self):
        with patch.object(type(self.ticket), '_run_ai_analysis', return_value=self.report), \
                patch.object(type(self.ticket), '_notify_support_channel'):
            self.ticket._analyze_and_notify()

    def test_email_queued_for_all_recipients(self):
        before = self._ticket_mails()
        self._analyze()
        mails = self._ticket_mails() - before
        self.assertEqual(len(mails), 1)
        self.assertEqual(mails.email_to, 'a@rmsproaudio.com,b@rmsproaudio.com')
        self.assertIn(self.ticket.name, mails.subject)
        self.assertEqual(mails.state, 'outgoing')
        self.assertTrue(mails.auto_delete)
        self.assertIn(self.report['summary'], mails.body_html)
        self.assertIn('Mensaje &lt;privado&gt;', mails.body_html)
        self.assertIn(
            self.ticket.get_base_url() + '/odoo/rms.support.ticket/%s' % self.ticket.id,
            mails.body_html,
        )

    def test_empty_parameter_disables_email(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'rms_support_error_report.notify_email', '',
        )
        before = self._ticket_mails()
        self._analyze()
        self.assertEqual(self._ticket_mails(), before)

    def test_duplicate_report_does_not_queue_email(self):
        before = self.Mail.search([])
        reporter = self.Ticket.with_user(self.reporter)
        payload = {'error_type': 'EmailDuplicateTest', 'error_message': 'Correo duplicado'}
        first = reporter.report_error(payload)
        self.assertEqual(first['status'], 'created')
        self.assertFalse(self.Mail.search([]) - before)
        second = reporter.report_error(payload)
        self.assertEqual(second['status'], 'duplicate')
        self.assertEqual(second['name'], first['name'])
        self.assertFalse(self.Mail.search([]) - before)

    def test_ai_failure_still_queues_email(self):
        before = self._ticket_mails()
        with patch.object(type(self.ticket), '_run_ai_analysis',
                          side_effect=RuntimeError('IA <no disponible>')), \
                patch.object(type(self.ticket), '_notify_support_channel'):
            self.ticket._analyze_and_notify()
        mails = self._ticket_mails() - before
        self.assertEqual(len(mails), 1)
        self.assertEqual(self.ticket.state, 'ai_failed')
        self.assertEqual(mails.state, 'outgoing')
        self.assertIn('No se ha podido generar el informe de la IA:', mails.body_html)
        self.assertIn('IA &lt;no disponible&gt;', mails.body_html)

    def test_channel_failure_still_queues_email(self):
        before = self._ticket_mails()
        with patch.object(type(self.ticket), '_run_ai_analysis', return_value=self.report), \
                patch.object(type(self.ticket), '_notify_support_channel',
                             side_effect=RuntimeError('Canal no disponible')):
            self.ticket._analyze_and_notify()
        self.assertEqual(len(self._ticket_mails() - before), 1)
