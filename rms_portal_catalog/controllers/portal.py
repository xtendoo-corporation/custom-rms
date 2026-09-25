import base64
import json
import mimetypes

from odoo import http
from odoo.http import request
from odoo.tools.mail import html2plaintext
from odoo.tools.misc import file_open

BASE_TAG = b'<base href="/my/catalog/">\n'
DEFAULT_REP = {
    'name': 'Salvador Escobar',
    'email': 'salva@rmsproaudio.com',
    'phone': '607 709 777',
}


class B2BCatalogPortal(http.Controller):

    def _current_rep(self):
        salesperson = request.env.user.partner_id.sudo().user_id
        if not salesperson:
            rep = dict(DEFAULT_REP)
        else:
            salesperson_partner = salesperson.partner_id
            rep = {
                'name': salesperson.name,
                'email': salesperson.email or salesperson.login,
                'phone': salesperson_partner.phone or salesperson_partner.mobile or DEFAULT_REP['phone'],
            }
        rep['photo'] = '/my/catalog/rep-photo'
        return rep

    @http.route('/my/catalog', type='http', auth='user')
    def portal_catalog_home(self, **kw):
        try:
            with file_open('rms_portal_catalog/static/catalog/index.html', 'rb') as f:
                content = f.read()
        except FileNotFoundError:
            return request.not_found()
        # Se escapa "<" para que un nombre/email con "</script>" no pueda
        # cortar el bloque script al incrustarlo en el HTML.
        rep_json = json.dumps(self._current_rep()).replace('<', '\\u003c')
        is_internal = request.env.user.has_group('base.group_user')
        injection = BASE_TAG + (
            '<script>\n'
            'window.RMS_CATALOG_REP = %s;\n'
            'window.RMS_CATALOG_IS_INTERNAL = %s;\n'
            '</script>\n' % (rep_json, 'true' if is_internal else 'false')
        ).encode('utf-8')
        return request.make_response(
            injection + content,
            headers=[('Content-Type', 'text/html; charset=utf-8')],
        )

    @http.route('/my/catalog/admin/card/<string:page_key>', type='http', auth='user')
    def portal_catalog_admin_card(self, page_key, **kw):
        if not request.env.user.has_group('base.group_user'):
            return request.not_found()
        Card = request.env['rms.catalog.card']
        card = Card.search([('page_key', '=', page_key)], limit=1)
        if not card:
            card = Card.create({'page_key': page_key})
        action = request.env.ref('rms_portal_catalog.action_rms_catalog_card')
        return request.redirect(
            '/web#model=rms.catalog.card&view_type=form&id=%d&action=%d' % (card.id, action.id)
        )

    def _catalog_card_get_or_create(self, page_key):
        Card = request.env['rms.catalog.card']
        card = Card.search([('page_key', '=', page_key)], limit=1)
        return card or Card.create({'page_key': page_key})

    @http.route('/my/catalog/admin/card/<string:page_key>/products', type='http', auth='user')
    def portal_catalog_admin_card_products(self, page_key, **kw):
        if not request.env.user.has_group('base.group_user'):
            return request.not_found()
        card = request.env['rms.catalog.card'].search([('page_key', '=', page_key)], limit=1)
        templates = card.line_ids.product_id.product_tmpl_id if card else request.env['product.template']
        payload = {
            'products': [
                {
                    'id': template.id,
                    'name': template.display_name,
                    'has_image': bool(template.image_128),
                }
                for template in templates
            ],
        }
        return request.make_response(
            json.dumps(payload),
            headers=[('Content-Type', 'application/json')],
        )

    @http.route('/my/catalog/admin/products/search', type='http', auth='user')
    def portal_catalog_admin_products_search(self, q='', **kw):
        if not request.env.user.has_group('base.group_user'):
            return request.not_found()
        q = (q or '').strip()
        domain = [('sale_ok', '=', True), ('active', '=', True)]
        if q:
            domain += ['|', ('name', 'ilike', q), ('default_code', 'ilike', q)]
        templates = request.env['product.template'].search(domain, limit=20)
        payload = {
            'products': [
                {
                    'id': template.id,
                    'name': template.display_name,
                    'has_image': bool(template.image_128),
                }
                for template in templates
            ],
        }
        return request.make_response(
            json.dumps(payload),
            headers=[('Content-Type', 'application/json')],
        )

    @http.route(
        '/my/catalog/admin/card/<string:page_key>/products/<int:template_id>/add',
        type='http', auth='user', methods=['POST'], csrf=False,
    )
    def portal_catalog_admin_card_add(self, page_key, template_id, **kw):
        if not request.env.user.has_group('base.group_user'):
            return request.not_found()
        template = request.env['product.template'].browse(template_id).exists()
        if template and template.product_variant_id:
            card = self._catalog_card_get_or_create(page_key)
            product = template.product_variant_id
            if product.id not in card.line_ids.product_id.ids:
                request.env['rms.catalog.card.line'].create({
                    'card_id': card.id,
                    'product_id': product.id,
                })
        return request.make_response(
            json.dumps({'ok': True}),
            headers=[('Content-Type', 'application/json')],
        )

    @http.route(
        '/my/catalog/admin/card/<string:page_key>/products/<int:template_id>/remove',
        type='http', auth='user', methods=['POST'], csrf=False,
    )
    def portal_catalog_admin_card_remove(self, page_key, template_id, **kw):
        if not request.env.user.has_group('base.group_user'):
            return request.not_found()
        card = request.env['rms.catalog.card'].search([('page_key', '=', page_key)], limit=1)
        if card:
            card.line_ids.filtered(
                lambda line: line.product_id.product_tmpl_id.id == template_id
            ).unlink()
        return request.make_response(
            json.dumps({'ok': True}),
            headers=[('Content-Type', 'application/json')],
        )

    @http.route('/my/catalog/rep-photo', type='http', auth='user')
    def portal_catalog_rep_photo(self, **kw):
        salesperson = request.env.user.partner_id.sudo().user_id
        if salesperson and salesperson.partner_id.image_128:
            content = base64.b64decode(salesperson.partner_id.image_128)
            return request.make_response(content, headers=[('Content-Type', 'image/png')])
        try:
            with file_open('rms_portal_catalog/static/catalog/images/reps/salvador-escobar.jpg', 'rb') as f:
                content = f.read()
        except FileNotFoundError:
            return request.not_found()
        return request.make_response(content, headers=[('Content-Type', 'image/jpeg')])

    @http.route('/my/catalog/prices/<string:page_key>', type='http', auth='user')
    def portal_catalog_prices(self, page_key, **kw):
        card = request.env['rms.catalog.card'].sudo().search([('page_key', '=', page_key)], limit=1)
        products = card.line_ids.product_id.product_tmpl_id.filtered(
            lambda tmpl: tmpl.sale_ok and tmpl.active
        ).sorted('list_price', reverse=True)
        payload = {
            'page_key': page_key,
            'products': [
                {
                    'id': product.id,
                    'name': product.display_name,
                    'description': html2plaintext(product.description or ''),
                    'list_price': product.list_price,
                    'has_image': bool(product.image_128),
                }
                for product in products
            ],
        }
        return request.make_response(
            json.dumps(payload),
            headers=[('Content-Type', 'application/json')],
        )

    @http.route('/my/catalog/product-image/<int:product_id>', type='http', auth='user')
    def portal_catalog_product_image(self, product_id, size=None, **kw):
        product = request.env['product.template'].sudo().browse(product_id).exists()
        image = product.image_1024 if size == 'full' else product.image_128
        if not product or not image:
            return request.not_found()
        content = base64.b64decode(image)
        return request.make_response(content, headers=[('Content-Type', 'image/png')])

    @http.route('/my/catalog/images/<path:subpath>', type='http', auth='user')
    def portal_catalog_asset(self, subpath, **kw):
        try:
            with file_open('rms_portal_catalog/static/catalog/images/%s' % subpath, 'rb') as f:
                content = f.read()
        except (FileNotFoundError, ValueError):
            return request.not_found()
        mimetype, _ = mimetypes.guess_type(subpath)
        return request.make_response(
            content,
            headers=[('Content-Type', mimetype or 'application/octet-stream')],
        )
