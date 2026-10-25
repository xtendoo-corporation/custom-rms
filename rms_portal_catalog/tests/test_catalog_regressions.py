import json
import shutil
import subprocess
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import patch

from odoo.http import Response
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user
from odoo.tools.misc import file_open

from ..controllers.portal import B2BCatalogPortal


@tagged('post_install', '-at_install')
class TestCatalogRegressions(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if cls.env.ref('custom.comerciales', raise_if_not_found=False) is None:
            group = cls.env['res.groups'].create({'name': 'Comerciales'})
            cls.env['ir.model.data'].create({
                'module': 'custom', 'name': 'comerciales',
                'model': 'res.groups', 'res_id': group.id,
            })
        cls.customer = new_test_user(
            cls.env, login='catalog_regression_customer', groups='base.group_portal',
        )
        cls.controller = B2BCatalogPortal()

    def _request(self, env=None):
        return patch('odoo.addons.rms_portal_catalog.controllers.portal.request', SimpleNamespace(
            env=env if env is not None else self.env,
            make_response=Response,
            redirect=lambda url: url,
        ))

    def test_prices_use_sale_description(self):
        product = self.env['product.product'].create({
            'name': 'Descripción del catálogo', 'sale_ok': True,
            'description': 'Nota interna confidencial',
            'description_sale': 'Descripción para el cliente',
        })
        self.env['rms.catalog.card'].create({
            'page_key': 'regression-description',
            'line_ids': [(0, 0, {'product_id': product.id})],
        })
        with self._request():
            response = self.controller.portal_catalog_prices('regression-description')
        payload = json.loads(response.get_data(as_text=True))
        self.assertEqual(len(payload['products']), 1)
        self.assertEqual(payload['products'][0]['description'], 'Descripción para el cliente')
        self.assertNotIn('Nota interna confidencial', json.dumps(payload))

    def test_cart_is_scoped_to_current_company(self):
        company = self.env.company
        other = self.env['res.company'].create({'name': 'Otra compañía catálogo'})
        # El sudo del controlador no debe permitir reutilizar este carrito.
        foreign_cart = self.env['sale.order'].with_company(other).create({
            'partner_id': self.customer.partner_id.id,
            'company_id': other.id, 'rms_portal_cart': True,
        })
        portal_env = self.customer.with_user(self.customer).with_context(
            allowed_company_ids=[company.id],
        ).env
        with self._request(portal_env):
            self.assertFalse(self.controller._get_portal_cart())
            cart = self.controller._get_portal_cart(create=True)
            self.assertNotEqual(cart.id, foreign_cart.id)
            self.assertEqual(cart.company_id, company)
            self.assertEqual(cart.pricelist_id, self.customer.partner_id.with_company(company).property_product_pricelist)
            self.assertEqual(self.controller._get_portal_cart(), cart)

    def test_admin_get_does_not_create_card(self):
        Card = self.env['rms.catalog.card']
        domain = [('page_key', '=', 'regression-empty-get')]
        self.assertFalse(Card.search(domain))
        with self._request():
            response = self.controller.portal_catalog_admin_card('regression-empty-get')
        self.assertIn('Sin productos asignados', response.get_data(as_text=True))
        self.assertFalse(Card.search(domain))

    def test_admin_post_add_creates_card(self):
        product = self.env['product.product'].create({'name': 'Primera asignación'})
        with self._request():
            self.controller.portal_catalog_admin_card_add('regression-first-save', product.product_tmpl_id.id)
        card = self.env['rms.catalog.card'].search([('page_key', '=', 'regression-first-save')])
        self.assertEqual(card.line_ids.product_id, product)

    @skipUnless(shutil.which('node'), 'La prueba del DOM necesita Node.js')
    def test_contact_and_product_text_cannot_inject_html(self):
        with file_open('rms_portal_catalog/catalog_private/index.html', 'r') as source:
            html = source.read()
        contact = html[html.index('function renderContact(){'):html.index('function renderBrand(')]
        helpers = html[html.index('function catalogNode('):html.index('async function openPrices(')]
        # DOM mínimo: ningún valor malicioso puede llegar a un sumidero HTML.
        script = r'''
const assert = require('node:assert/strict');
const attack = '<img src=x onerror="alert(1)">';
class Element {
  constructor(tag){ this.tag = tag; this.children = []; this.attrs = {}; }
  setAttribute(key, value){ this.attrs[key] = String(value); }
  append(...nodes){ this.children.push(...nodes); }
  set innerHTML(value){ assert.ok(!value.includes(attack)); }
  addEventListener(){}
}
const document = {createElement: tag => new Element(tag)};
const grid = new Element('div');
const app = new Element('main');
app.querySelector = () => grid;
const shell = text => text;
const bindSearch = () => {};
let REPS = [{name: attack, email: attack, phone: attack, photo: attack}];
''' + contact + helpers + r'''
renderContact();
const card = grid.children[0];
assert.equal(card.children[0].attrs.src, attack);
const info = card.children[1];
assert.equal(info.children[0].textContent, attack);
for(const line of info.children.slice(1)){
  assert.equal(line.tag, 'span');
  assert.equal(line.textContent, attack);
  assert.equal(line.attrs.href, undefined);
}
REPS = [{name: 'Comercial', email: 'ventas@example.com', phone: '+34 (955) 123-456', photo: '/photo'}];
renderContact();
const links = grid.children[1].children[1].children;
assert.equal(links[1].attrs.href, 'mailto:ventas@example.com');
assert.equal(links[2].attrs.href, 'tel:+34 (955) 123-456');
const formatEUR = String;
const qtyControlHtml = () => '';
const product = productRow({id: 1, name: attack, description: attack, list_price: 10}, {prices: true});
assert.equal(product.children[0].children[0].textContent, attack);
assert.equal(product.children[0].children[1].textContent, attack);
'''
        result = subprocess.run(
            [shutil.which('node'), '-'], input=script, text=True,
            capture_output=True, timeout=20, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
