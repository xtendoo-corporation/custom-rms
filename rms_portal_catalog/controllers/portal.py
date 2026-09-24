import mimetypes

from odoo import http
from odoo.http import request
from odoo.tools.misc import file_open

BASE_TAG = b'<base href="/my/catalog/">\n'


class B2BCatalogPortal(http.Controller):

    @http.route('/my/catalog', type='http', auth='user', website=True)
    def portal_catalog_home(self, **kw):
        try:
            with file_open('rms_portal_catalog/static/catalog/index.html', 'rb') as f:
                content = BASE_TAG + f.read()
        except FileNotFoundError:
            return request.not_found()
        return request.make_response(
            content,
            headers=[('Content-Type', 'text/html; charset=utf-8')],
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
