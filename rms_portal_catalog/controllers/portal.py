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

    @http.route('/my/catalog', type='http', auth='user', website=True)
    def portal_catalog_home(self, **kw):
        try:
            with file_open('rms_portal_catalog/static/catalog/index.html', 'rb') as f:
                content = f.read()
        except FileNotFoundError:
            return request.not_found()
        # Se escapa "<" para que un nombre/email con "</script>" no pueda
        # cortar el bloque script al incrustarlo en el HTML.
        rep_json = json.dumps(self._current_rep()).replace('<', '\\u003c')
        injection = BASE_TAG + ('<script>window.RMS_CATALOG_REP = %s;</script>\n' % rep_json).encode('utf-8')
        return request.make_response(
            injection + content,
            headers=[('Content-Type', 'text/html; charset=utf-8')],
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

    @http.route('/my/catalog/prices/<int:category_id>', type='http', auth='user')
    def portal_catalog_prices(self, category_id, **kw):
        products = request.env['product.template'].sudo().search(
            [('categ_id', '=', category_id), ('sale_ok', '=', True), ('active', '=', True)],
            order='list_price desc',
        )
        payload = {
            'category_id': category_id,
            'products': [
                {
                    'id': product.id,
                    'name': product.display_name,
                    'description': html2plaintext(product.description or ''),
                    'list_price': product.list_price,
                }
                for product in products
            ],
        }
        return request.make_response(
            json.dumps(payload),
            headers=[('Content-Type', 'application/json')],
        )

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
