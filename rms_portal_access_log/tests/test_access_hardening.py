from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import HttpCase, TransactionCase, new_test_user


@tagged('post_install', '-at_install')
class TestAccessHardening(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = new_test_user(cls.env, login='log_employee', groups='base.group_user')
        cls.reader = new_test_user(
            cls.env, login='log_reader',
            groups='rms_portal_access_log.group_portal_weekly_report',
        )
        cls.other_company = cls.env['res.company'].create({'name': 'Portal compañía B'})
        cls.partner_b = cls.env['res.partner'].create({
            'name': 'Cliente B', 'company_id': cls.other_company.id,
        })

    def test_employee_cannot_read_logs(self):
        for model in ('rms.portal.access.log', 'rms.portal.activity', 'rms.portal.interest'):
            with self.subTest(model=model), self.assertRaises(AccessError):
                self.env[model].with_user(self.employee).search([])

    def test_company_rules(self):
        access = self.env['rms.portal.access.log'].create({
            'partner_id': self.partner_b.id, 'login_date': fields.Datetime.now(),
        })
        activity = self.env['rms.portal.activity'].create({
            'partner_id': self.partner_b.id, 'activity_type': 'card', 'page_key': 'company-b',
        })
        self.env.flush_all()
        interest = self.env['rms.portal.interest'].search([('partner_id', '=', self.partner_b.id)])
        self.assertTrue(interest)
        for record in (access, activity, interest):
            scoped = record.with_user(self.reader).with_context(allowed_company_ids=[self.reader.company_id.id])
            self.assertFalse(scoped.search([('id', 'in', record.ids)]))
            with self.assertRaises(AccessError):
                scoped.read(['partner_id'])
        # Los contactos compartidos siguen siendo visibles.
        self.partner_b.company_id = False
        self.assertTrue(activity.with_user(self.reader).search([('id', '=', activity.id)]))

    def test_retention(self):
        now = fields.Datetime.now()
        self.env['ir.config_parameter'].sudo().set_param('rms_portal_access_log.retention_days', 10)
        for model, date_field, extra in (
            ('rms.portal.access.log', 'login_date', {}),
            ('rms.portal.activity', 'date', {'activity_type': 'card'}),
        ):
            old = self.env[model].create({date_field: now - timedelta(days=11), **extra})
            recent = self.env[model].create({date_field: now - timedelta(days=9), **extra})
            self.env['rms.portal.access.log']._cron_purge_old_logs()
            self.assertFalse(old.exists())
            self.assertTrue(recent.exists())

    def test_event_rate_limit(self):
        portal = new_test_user(self.env, login='rate_portal', groups='base.group_portal')
        Activity = self.env['rms.portal.activity']
        Activity.create([{
            'activity_type': 'quote_add', 'user_id': portal.id,
            'partner_id': portal.partner_id.id,
        } for _ in range(60)])
        self.assertFalse(Activity.with_user(portal)._log('quote_add', name='Evento 61'))
        self.assertEqual(Activity.search_count([('user_id', '=', portal.id)]), 60)


@tagged('post_install', '-at_install')
class TestTrackCsrf(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        new_test_user(cls.env, login='csrf_portal', password='csrf_portal', groups='base.group_portal')

    def test_track_without_csrf_is_rejected(self):
        self.authenticate('csrf_portal', 'csrf_portal')
        response = self.url_open('/my/portal/track', data={'kind': 'card', 'key': 'csrf-test'})
        self.assertEqual(response.status_code, 400)
