import base64
import json
from urllib.parse import urlparse
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tests.common import HttpCase, TransactionCase, new_test_user
from odoo.tools import mute_logger
from odoo.tools.safe_eval import safe_eval
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestInstallationProjectPortalProfile(TransactionCase):
    def test_manager_reads_partner_portal_profile(self):
        manager = new_test_user(
            self.env, login='profile_project_manager',
            groups='rms_portal_projects.group_installation_project_manager',
        )
        self.assertFalse(manager.has_group('base.group_erp_manager'))
        self.assertFalse(manager.has_group('base.group_system'))
        for profile in ('customer', 'marketing', 'projects'):
            with self.subTest(profile=profile):
                partner = self.env['res.partner'].create({
                    'name': 'Profile customer', 'portal_profile': profile,
                })
                project = self.env['rms.installation.project'].create({
                    'name': 'Portal profile', 'partner_id': partner.id,
                })
                self.env.invalidate_all()
                self.assertEqual(partner.with_user(manager).read(['portal_profile'])[0]['portal_profile'], profile)
                self.assertEqual(
                    project.with_user(manager).read(['partner_portal_profile'])[0]['partner_portal_profile'],
                    profile,
                )


@tagged('post_install', '-at_install')
class TestInstallationProjectSendMessage(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(
            cls.env, login='send_project_manager',
            groups='rms_portal_projects.group_installation_project_manager',
        )

    def _project(self, partner):
        return self.env['rms.installation.project'].with_user(self.manager).create({
            'name': 'Proyecto envío', 'partner_id': partner.id,
            'file_name': 'proyecto.html',
            'file_data': base64.b64encode(b'<html>Proyecto</html>'),
        })

    def _send_message(self, project):
        with patch.object(type(self.env['portal.wizard.user']), '_send_email', return_value=True):
            action = project.action_send()
        return self.env[action['res_model']].with_user(self.manager).browse(action['res_id']).message

    def test_manager_sends_to_new_customer(self):
        self.assertFalse(self.manager.has_group('base.group_erp_manager'))
        partner = self.env['res.partner'].create({
            'name': 'Nuevo cliente', 'email': 'send-new@example.com',
            'portal_profile': 'projects',
        })
        project = self._project(partner)
        message = self._send_message(project)
        self.assertEqual(project.state, 'sent')
        self.assertTrue(partner.user_ids.share)
        self.assertTrue(partner.user_ids.has_group('base.group_portal'))
        self.assertTrue(partner.user_ids.has_group('rms_portal_profiles.group_portal_customer'))
        self.assertIn('/web/login?', message)
        self.assertIn('Es tu primer acceso:', message)
        self.assertIn('/my/installation-projects/%s' % project.id, message)

    def test_manager_sends_to_active_customer_without_signup(self):
        user = new_test_user(
            self.env, login='send_active_portal', groups='base.group_portal',
            email='send-active@example.com',
        )
        user.with_user(user).sudo()._update_last_login()
        project = self._project(user.partner_id)
        with patch.object(type(self.env['rms.portal.invite.link']), '_prepare_for_partner') as prepare:
            message = self._send_message(project)
        prepare.assert_not_called()
        self.assertEqual(project.state, 'sent')
        self.assertNotIn('/web/login?', message)
        self.assertNotIn('Es tu primer acceso:', message)
        self.assertIn('/my/installation-projects/%s' % project.id, message)

    def test_internal_customer_stays_draft(self):
        project = self._project(self.manager.partner_id)
        with self.assertRaisesRegex(UserError, 'El cliente es un usuario interno; elige un contacto de cliente.'):
            project.action_send()
        self.assertEqual(project.state, 'draft')

    def test_project_invite_delegates_to_contact(self):
        project = self._project(self.manager.partner_id)
        expected = {'type': 'ir.actions.act_window', 'res_id': 123, 'target': 'new'}
        with patch.object(type(self.env['res.partner']), 'action_open_portal_invite_link', autospec=True, return_value=expected) as action:
            self.assertEqual(project.action_open_portal_invite_link(), expected)
        action.assert_called_once_with(project.partner_id)

    def test_missing_email_stays_draft(self):
        partner = self.env['res.partner'].create({'name': 'Sin correo'})
        project = self._project(partner)
        with self.assertRaisesRegex(UserError, 'no tiene correo electrónico'):
            project.action_send()
        self.assertEqual(project.state, 'draft')


@tagged('post_install', '-at_install')
class TestPortalProfileSecurity(AccountTestInvoicingCommon, HttpCase):
    """Kept in an already discovered test module: no __init__ test imports added."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer_company = cls.env['res.partner'].create({
            'name': 'S4 customer company', 'is_company': True,
            'property_account_receivable_id': cls.company_data['default_account_receivable'].id,
            'property_account_payable_id': cls.company_data['default_account_payable'].id,
        })
        cls.profile_users = {}
        for profile in ('customer', 'projects', 'marketing'):
            user = new_test_user(
                cls.env, login='s4_' + profile, password='s4_password',
                groups='base.group_portal', company_id=cls.env.company.id,
            )
            user.partner_id.write({
                'parent_id': cls.customer_company.id, 'portal_profile': profile,
            })
            cls.profile_users[profile] = user
        cls.sales_user = new_test_user(
            cls.env, login='s4_sales', groups='sales_team.group_sale_salesman',
            company_id=cls.env.company.id,
        )
        cls.order = cls.env['sale.order'].sudo().create({
            'partner_id': cls.customer_company.id, 'user_id': cls.sales_user.id,
            'order_line': [Command.create({
                'product_id': cls.product_a.id, 'product_uom_qty': 1, 'price_unit': 100,
            })],
        })
        cls.order.action_confirm()
        cls.invoice = cls.env['account.move'].sudo().create({
            'move_type': 'out_invoice', 'partner_id': cls.customer_company.id,
            'journal_id': cls.company_data['default_journal_sale'].id,
            'invoice_line_ids': [Command.create({
                'product_id': cls.product_a.id, 'quantity': 1, 'price_unit': 100,
                'account_id': cls.company_data['default_account_revenue'].id,
            })],
        })
        cls.invoice.action_post()
        cls.order_token = cls.order._portal_ensure_token()
        cls.invoice_token = cls.invoice._portal_ensure_token()
        cls.installation = cls.env['rms.installation.project'].sudo().create({
            'name': 'S4 installation', 'partner_id': cls.profile_users['marketing'].partner_id.id,
            'state': 'sent', 'file_name': 's4.html',
            'file_data': base64.b64encode(b'<html><body>S4 installation</body></html>'),
        })

    def _assert_redirect_my(self, url):
        response = self.url_open(url, allow_redirects=False)
        self.assertIn(response.status_code, (302, 303))
        self.assertEqual(urlparse(response.headers['Location']).path, '/my')

    def test_customer_orm_and_order_detail(self):
        user = self.profile_users['customer']
        for record in (self.order, self.invoice):
            self.assertEqual(record.with_user(user).read(['name'])[0]['name'], record.name)
        self.authenticate(user.login, 's4_password')
        self.assertEqual(self.url_open('/my/orders/%s' % self.order.id).status_code, 200)
        self.assertEqual(self.url_open('/my/invoices/%s' % self.invoice.id).status_code, 200)

    def test_non_customer_orm_and_rules(self):
        records = (self.order, self.order.order_line, self.invoice, self.invoice.line_ids)
        for profile in ('projects', 'marketing'):
            user = self.profile_users[profile]
            for record in records:
                model = self.env[record._name].with_user(user)
                domain = [('id', 'in', record.ids)]
                if model.has_access('read'):
                    self.assertFalse(model.search(domain))
                    self.assertEqual(model.search_count(domain), 0)
                else:
                    with self.assertRaises(AccessError):
                        model.search(domain)
                with self.assertRaises(AccessError):
                    record.with_user(user).read(['name'])
        # Actual Odoo safe_eval, not Python eval: exercise every branch and mode.
        for model in ('sale_order', 'sale_order_line', 'account_move', 'account_move_line', 'account_payment'):
            rule = self.env.ref('rms_portal_profiles.%s_portal_customer_profile_rule' % model)
            self.assertTrue(rule['global'])
            self.assertTrue(all(rule['perm_' + mode] for mode in ('read', 'write', 'create', 'unlink')))
            for user, allowed in (
                (self.profile_users['customer'], True), (self.profile_users['projects'], False),
                (self.profile_users['marketing'], False), (self.sales_user, True),
                (self.env.ref('base.public_user'),
                 self.env.ref('base.public_user').has_group('rms_portal_profiles.group_portal_customer')),
            ):
                self.assertEqual(safe_eval(rule.domain_force, {'user': user.sudo()}),
                                 [(1, '=', 1)] if allowed else [(0, '=', 1)])
        self.assertEqual(self.order.with_user(self.sales_user).read(['name'])[0]['name'], self.order.name)
        self.assertEqual(self.order.with_user(self.profile_users['projects']).sudo().name, self.order.name)

    @mute_logger('odoo.http')
    def test_projects_http_and_counters(self):
        user = self.profile_users['projects']
        self.authenticate(user.login, 's4_password')
        for url, token in (
            ('/my/orders/%s' % self.order.id, self.order_token),
            ('/my/invoices/%s' % self.invoice.id, self.invoice_token),
        ):
            self._assert_redirect_my(url)
            self._assert_redirect_my(url + '?access_token=' + token)
            self._assert_redirect_my(url + '?report_type=pdf&access_token=' + token)
        response = self.url_open('/report/pdf/sale.report_saleorder/%s' % self.order.id)
        self.assertNotEqual(response.headers.get('Content-Type', '').split(';')[0], 'application/pdf')
        self.assertFalse(response.content.startswith(b'%PDF'))
        self.assertEqual(self.url_open('/my/home').status_code, 200)
        counters = ['order_count', 'quotation_count', 'invoice_count', 'overdue_invoice_count']
        response = self.url_open('/my/counters', data=json.dumps({
            'jsonrpc': '2.0', 'method': 'call', 'params': {'counters': counters}, 'id': 1,
        }), headers={'Content-Type': 'application/json'})
        values = response.json()
        self.assertNotIn('error', values)
        for counter in counters:
            self.assertEqual(values['result'][counter], 0)

    def test_anonymous_token_links(self):
        self.authenticate(None, None)
        for url, token in (
            ('/my/orders/%s' % self.order.id, self.order_token),
            ('/my/invoices/%s' % self.invoice.id, self.invoice_token),
        ):
            self._assert_redirect_my(url)
            response = self.url_open(url + '?access_token=' + token, allow_redirects=False)
            self.assertEqual(response.status_code, 200)

    def test_marketing_installation_detail_and_file(self):
        self.authenticate(self.profile_users['marketing'].login, 's4_password')
        url = '/my/installation-projects/%s' % self.installation.id
        self._assert_redirect_my(url)
        self._assert_redirect_my(url + '/file')

    def test_installation_profile_field_internal_only(self):
        self.assertEqual(self.installation._fields['partner_portal_profile'].groups, 'base.group_user')
        with self.assertRaises(AccessError):
            self.installation.with_user(self.profile_users['marketing']).read(['partner_portal_profile'])
