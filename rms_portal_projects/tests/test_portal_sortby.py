from lxml import html

from odoo.tests import HttpCase, tagged
from odoo.tests.common import new_test_user


@tagged('post_install', '-at_install')
class TestPortalProjectSortby(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        groups = 'base.group_portal'
        if cls.env.ref('rms_portal_profiles.group_portal_projects', raise_if_not_found=False):
            groups += ',rms_portal_profiles.group_portal_projects'
        cls.customer = new_test_user(
            cls.env, login='portal_sortby_customer', groups=groups,
        )
        # Las fechas y las referencias tienen órdenes opuestos.
        cls.older_project = cls.env['rms.installation.project'].create({
            'name': 'A - Proyecto antiguo', 'date': '2026-01-01',
            'partner_id': cls.customer.partner_id.id, 'state': 'sent',
        })
        cls.newer_project = cls.env['rms.installation.project'].create({
            'name': 'Z - Proyecto reciente', 'date': '2026-02-01',
            'partner_id': cls.customer.partner_id.id, 'state': 'sent',
        })

    def test_invalid_sortby_uses_date(self):
        self.authenticate(self.customer.login, self.customer.login)
        response = self.url_open('/my/installation-projects?sortby=no-existe')
        self.assertEqual(response.status_code, 200)
        # Verifica el orden real y evita que una redirección al portal pase el test.
        document = html.fromstring(response.content)
        project_links = document.xpath(
            '//table[contains(@class, "o_portal_my_doc_table")]/tbody/tr/td/a/@href',
        )
        self.assertEqual(project_links, [
            '/my/installation-projects/%s' % self.newer_project.id,
            '/my/installation-projects/%s' % self.older_project.id,
        ])
