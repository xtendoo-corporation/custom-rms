import base64
import io
import json
import logging
import mimetypes
import os
import re
from functools import lru_cache

from PIL import Image

from odoo import http
from odoo.http import content_disposition, request
from odoo.tools.mail import html2plaintext
from odoo.tools.misc import file_open, file_path

BASE_TAG = b'<base href="/my/catalog/">\n'
MAX_PDF_PAGES = 200
A4_WIDTH_PT = 595.28

_logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def catalog_metadata():
    """Read deployment-static JS metadata without executing JavaScript.

    The objects use JSON strings, unquoted keys, trailing commas and LOGO
    references. Tokenizing strings first preserves braces/commas inside text.
    Any unsupported syntax or incomplete metadata disables the whole result.
    """
    try:
        with file_open('rms_portal_catalog/catalog_private/index.html', 'r') as source:
            content = source.read()
        objects = {}
        token_re = re.compile(
            r'"(?:[^"\\]|\\.)*"|//[^\n]*|/\*.*?\*/|'
            r'LOGO\.[A-Za-z_$][\w$]*|[A-Za-z_$][\w$]*|'
            r'-?\d+(?:\.\d+)?|[{}\[\]:,]|\s+', re.DOTALL,
        )
        for name in ('PAGES', 'BRANDS'):
            declaration = re.search(r'\bconst\s+' + name + r'\s*=\s*(?={)', content)
            if not declaration:
                raise ValueError('Missing %s declaration' % name)
            position = declaration.end()
            depth = 0
            tokens = []
            while position < len(content):
                match = token_re.match(content, position)
                if not match:
                    raise ValueError('Unsupported syntax in %s' % name)
                token = match.group()
                position = match.end()
                if token.isspace() or token.startswith(('//', '/*')):
                    continue
                if token in ('{', '['):
                    depth += 1
                elif token in ('}', ']'):
                    depth -= 1
                if token.startswith('LOGO.'):
                    token = 'null'
                elif token[0] != '"' and re.fullmatch(r'[\w$]+', token):
                    # Numeric page keys and JS identifiers become JSON keys.
                    if re.match(r'\s*:', content[position:]):
                        token = json.dumps(token)
                    elif token not in ('true', 'false', 'null') and not token.isdigit():
                        raise ValueError('Unsupported value in %s' % name)
                if token in ('}', ']') and tokens[-1:] == [',']:
                    tokens.pop()
                tokens.append(token)
                if depth == 0:
                    break
            objects[name] = json.loads(''.join(tokens))
        brands = {key: {'name': value['name']} for key, value in objects['BRANDS'].items()}
        pages = {key: {'title': value['title'], 'brand': value['brand']}
                 for key, value in objects['PAGES'].items()}
        if (not pages or not brands
                or any(not isinstance(b['name'], str) or not b['name'] for b in brands.values())
                or any(not isinstance(p['title'], str) or not p['title']
                       or p['brand'] not in brands for p in pages.values())):
            raise ValueError('Invalid catalog metadata')
        return pages, brands
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        _logger.warning('Unable to parse catalog PAGES/BRANDS metadata', exc_info=True)
        return {}, {}


def _jpegs_to_pdf(jpegs, title=''):
    """Une imágenes JPEG en un PDF, una por página, sin recomprimirlas.

    Cada JPEG se incrusta tal cual (filtro DCTDecode), así que la calidad
    es la del catálogo y el PDF se genera al instante.
    """
    objects = []  # contenido de cada objeto; su número es índice + 1

    def add(content):
        objects.append(content)
        return len(objects)

    catalog_id = add(None)
    pages_id = add(None)
    page_ids = []
    for jpeg in jpegs:
        img = Image.open(io.BytesIO(jpeg))
        width, height = img.size
        color_space = {'L': '/DeviceGray', 'CMYK': '/DeviceCMYK'}.get(img.mode, '/DeviceRGB')
        decode = ' /Decode [1 0 1 0 1 0 1 0]' if img.mode == 'CMYK' else ''
        page_w, page_h = A4_WIDTH_PT, A4_WIDTH_PT * height / width
        image_id = add(
            ('<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace %s'
             ' /BitsPerComponent 8 /Filter /DCTDecode%s /Length %d >>\nstream\n'
             % (width, height, color_space, decode, len(jpeg))).encode() + jpeg + b'\nendstream'
        )
        drawing = b'q %.2f 0 0 %.2f 0 0 cm /Im0 Do Q' % (page_w, page_h)
        content_id = add(b'<< /Length %d >>\nstream\n%s\nendstream' % (len(drawing), drawing))
        page_ids.append(add(
            b'<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.2f %.2f]'
            b' /Resources << /XObject << /Im0 %d 0 R >> >> /Contents %d 0 R >>'
            % (pages_id, page_w, page_h, image_id, content_id)
        ))
    objects[catalog_id - 1] = b'<< /Type /Catalog /Pages %d 0 R >>' % pages_id
    objects[pages_id - 1] = b'<< /Type /Pages /Kids [%s] /Count %d >>' % (
        b' '.join(b'%d 0 R' % pid for pid in page_ids), len(page_ids),
    )
    title_hex = ('feff' + title.encode('utf-16-be').hex()).encode()
    info_id = add(b'<< /Title <%s> /Producer (RMS Proaudio) >>' % title_hex)

    out = io.BytesIO()
    out.write(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
    offsets = []
    for number, content in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(b'%d 0 obj\n' % number + content + b'\nendobj\n')
    xref = out.tell()
    out.write(b'xref\n0 %d\n0000000000 65535 f \n' % (len(objects) + 1))
    out.write(b''.join(b'%010d 00000 n \n' % offset for offset in offsets))
    out.write(b'trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (
        len(objects) + 1, catalog_id, info_id, xref,
    ))
    return out.getvalue()
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
            with file_open('rms_portal_catalog/catalog_private/index.html', 'rb') as f:
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
            'window.RMS_CSRF = %s;\n'
            '</script>\n' % (rep_json, 'true' if is_internal else 'false',
                               json.dumps(request.csrf_token()))
        ).encode('utf-8')
        return request.make_response(
            injection + content,
            headers=[('Content-Type', 'text/html; charset=utf-8'),
                     ('Cache-Control', 'private, no-store')],
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
        featured_ids = set(card.line_ids.filtered('featured').product_id.product_tmpl_id.ids)
        payload = {
            'products': [
                {
                    'id': template.id,
                    'name': template.display_name,
                    'has_image': bool(template.image_128),
                    'featured': template.id in featured_ids,
                }
                for template in templates.sorted(lambda t: t.id in featured_ids, reverse=True)
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
        type='http', auth='user', methods=['POST'],
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
        type='http', auth='user', methods=['POST'],
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

    @http.route(
        '/my/catalog/admin/card/<string:page_key>/products/<int:template_id>/featured',
        type='http', auth='user', methods=['POST'],
    )
    def portal_catalog_admin_card_featured(self, page_key, template_id, **kw):
        """Marca o desmarca un producto de la ficha como destacado (solo internos)."""
        if not request.env.user.has_group('base.group_user'):
            return request.not_found()
        card = request.env['rms.catalog.card'].search([('page_key', '=', page_key)], limit=1)
        lines = card.line_ids.filtered(lambda line: line.product_id.product_tmpl_id.id == template_id)
        featured = not any(lines.mapped('featured'))
        lines.write({'featured': featured})
        return request.make_response(
            json.dumps({'ok': bool(lines), 'featured': featured if lines else False}),
            headers=[('Content-Type', 'application/json')],
        )

    @http.route('/my/catalog/brand-pdf/<string:brand>', type='http', auth='user')
    def portal_catalog_brand_pdf(self, brand, pages='', name='', **kw):
        """PDF con todas las páginas de una marca, en el orden del catálogo.

        Las páginas (números de imagen) las manda el catálogo, que es quien
        conoce qué páginas son de cada marca; aquí solo se aceptan números y
        solo se sirven imágenes del propio catálogo.
        """
        if not re.fullmatch(r'[a-z0-9_-]{1,40}', brand or ''):
            return request.not_found()
        numbers = []
        for token in (pages or '').split(','):
            if token.strip().isdigit() and int(token) not in numbers:
                numbers.append(int(token))
        images = []
        for number in numbers[:MAX_PDF_PAGES]:
            try:
                with file_open('rms_portal_catalog/catalog_private/images/full/p%03d.jpg' % number, 'rb') as f:
                    images.append(f.read())
            except FileNotFoundError:
                continue
        if not images:
            return request.not_found()
        title = re.sub(r'[^\w .&-]', '', name or brand)[:60].strip() or brand
        pdf = _jpegs_to_pdf(images, title='Catálogo %s - RMS Proaudio' % title)
        return request.make_response(pdf, headers=[
            ('Content-Type', 'application/pdf'),
            ('Content-Length', len(pdf)),
            ('Content-Disposition', content_disposition('Catálogo %s - RMS Proaudio.pdf' % title)),
        ])

    @http.route('/my/catalog/rep-photo', type='http', auth='user')
    def portal_catalog_rep_photo(self, **kw):
        salesperson = request.env.user.partner_id.sudo().user_id
        if salesperson and salesperson.partner_id.image_128:
            content = base64.b64decode(salesperson.partner_id.image_128)
            return request.make_response(content, headers=[('Content-Type', 'image/png'),
                ('Cache-Control', 'private, max-age=86400'),
                ('X-Content-Type-Options', 'nosniff')])
        try:
            with file_open('rms_portal_catalog/catalog_private/images/reps/salvador-escobar.jpg', 'rb') as f:
                content = f.read()
        except FileNotFoundError:
            return request.not_found()
        return request.make_response(content, headers=[('Content-Type', 'image/jpeg'),
                ('Cache-Control', 'private, max-age=86400'),
                ('X-Content-Type-Options', 'nosniff')])

    def _allowed_catalog_products(self, template_id=None, page_key=None):
        """Only linked, sellable active variants in the user's company scope."""
        cards = request.env['rms.catalog.card'].sudo().search(
            [('active', '=', True)] + ([('page_key', '=', page_key)] if page_key is not None else [])
        )
        domain = [
            ('id', 'in', cards.line_ids.product_id.ids),
            ('sale_ok', '=', True), ('active', '=', True),
            ('product_tmpl_id.active', '=', True),
            ('company_id', 'in', [False, request.env.user.company_id.id]),
        ]
        if template_id is not None:
            try:
                template_id = int(template_id)
            except (TypeError, ValueError):
                return request.env['product.product'].sudo().browse([])
            domain.append(('product_tmpl_id', '=', template_id))
        return request.env['product.product'].sudo().search(domain)

    @http.route('/my/catalog/prices/<string:page_key>', type='http', auth='user')
    def portal_catalog_prices(self, page_key, **kw):
        card = request.env['rms.catalog.card'].sudo().search([('page_key', '=', page_key)], limit=1)
        featured_ids = set(card.line_ids.filtered('featured').product_id.product_tmpl_id.ids)
        products = self._allowed_catalog_products(page_key=page_key).product_tmpl_id.sorted(
            lambda tmpl: (tmpl.id in featured_ids, tmpl.list_price), reverse=True,
        )
        payload = {
            'page_key': page_key,
            'products': [
                {
                    'id': product.id,
                    'name': product.display_name,
                    'description': html2plaintext(product.description or ''),
                    'list_price': product.list_price,
                    'has_image': bool(product.image_128),
                    'featured': product.id in featured_ids,
                }
                for product in products
            ],
        }
        return request.make_response(
            json.dumps(payload),
            headers=[('Content-Type', 'application/json')],
        )

    def _get_portal_cart(self, create=False):
        partner = request.env.user.partner_id
        Order = request.env['sale.order'].sudo()
        order = Order.search([
            ('partner_id', '=', partner.id),
            ('rms_portal_cart', '=', True),
            ('state', '=', 'draft'),
        ], order='create_date desc', limit=1)
        if not order and create:
            vals = {
                'partner_id': partner.id,
                'pricelist_id': partner.property_product_pricelist.id,
                'rms_portal_cart': True,
            }
            # Defined in rms_document_format (optional dependency).
            if 'rms_hide_price_detail' in Order._fields:
                vals['rms_hide_price_detail'] = True
            order = Order.create(vals)
        return order

    def _portal_cart_payload(self, order):
        if not order:
            return {'order_id': None, 'count': 0, 'lines': []}
        return {
            'order_id': order.id,
            'count': int(sum(order.order_line.mapped('product_uom_qty'))),
            'lines': [
                {
                    'product_id': line.product_id.product_tmpl_id.id,
                    'name': line.product_id.display_name,
                    'qty': line.product_uom_qty,
                    'price_subtotal': line.price_subtotal,
                }
                for line in order.order_line
            ],
        }

    @http.route('/my/catalog/quote', type='http', auth='user')
    def portal_catalog_quote(self, **kw):
        order = self._get_portal_cart()
        return request.make_response(
            json.dumps(self._portal_cart_payload(order)),
            headers=[('Content-Type', 'application/json')],
        )

    @http.route('/my/catalog/quote/pdf', type='http', auth='user')
    def portal_catalog_quote_pdf(self, **kw):
        order = self._get_portal_cart()
        if not order or not order.order_line:
            return request.not_found()
        pdf_content, _ = request.env['ir.actions.report'].sudo()._render_qweb_pdf(
            'sale.action_report_saleorder', [order.id],
        )
        filename = 'Presupuesto %s.pdf' % (order.name or order.id)
        return request.make_response(
            pdf_content,
            headers=[
                ('Content-Type', 'application/pdf'),
                ('Content-Disposition', 'attachment; filename="%s"' % filename),
            ],
        )

    @http.route('/my/catalog/quote/add', type='http', auth='user', methods=['POST'])
    def portal_catalog_quote_add(self, product_id, **kw):
        products = self._allowed_catalog_products(template_id=product_id)
        if not products:
            return request.not_found()
        order = self._get_portal_cart(create=True)
        variant = products[:1]
        line = order.order_line.filtered(lambda l: l.product_id.id == variant.id)
        if line:
            line.product_uom_qty += 1
        else:
            request.env['sale.order.line'].sudo().create({
                'order_id': order.id,
                'product_id': variant.id,
                'product_uom_qty': 1,
            })
        return request.make_response(
            json.dumps(self._portal_cart_payload(order)),
            headers=[('Content-Type', 'application/json')],
        )

    def _portal_cart_product_lines(self, order, template_id):
        """Resolve only lines in the partner-scoped cart, even if no longer sold."""
        try:
            template_id = int(template_id)
        except (TypeError, ValueError):
            return order.order_line.browse([])
        return order.order_line.filtered(
            lambda line: line.product_id.product_tmpl_id.id == template_id
        )

    @http.route('/my/catalog/quote/decrease', type='http', auth='user', methods=['POST'])
    def portal_catalog_quote_decrease(self, product_id, **kw):
        """Quita una unidad; si era la última, quita la línea."""
        order = self._get_portal_cart(create=False)
        lines = self._portal_cart_product_lines(order, product_id)
        if not lines:
            return request.not_found()
        for line in lines:
            if line.product_uom_qty > 1:
                line.product_uom_qty -= 1
            else:
                line.unlink()
        return request.make_response(
            json.dumps(self._portal_cart_payload(order)),
            headers=[('Content-Type', 'application/json')],
        )

    @http.route('/my/catalog/quote/remove', type='http', auth='user', methods=['POST'])
    def portal_catalog_quote_remove(self, product_id, **kw):
        order = self._get_portal_cart(create=False)
        lines = self._portal_cart_product_lines(order, product_id)
        if not lines:
            return request.not_found()
        lines.unlink()
        return request.make_response(
            json.dumps(self._portal_cart_payload(order)),
            headers=[('Content-Type', 'application/json')],
        )

    @http.route('/my/catalog/product-image/<int:product_id>', type='http', auth='user')
    def portal_catalog_product_image(self, product_id, size=None, **kw):
        products = self._allowed_catalog_products(template_id=product_id)
        if not products:
            return request.not_found()
        product = products.product_tmpl_id
        image = product.image_1024 if size == 'full' else product.image_128
        if not product or not image:
            return request.not_found()
        content = base64.b64decode(image)
        return request.make_response(content, headers=[('Content-Type', 'image/png'),
                ('Cache-Control', 'private, max-age=86400'),
                ('X-Content-Type-Options', 'nosniff')])

    @http.route('/my/catalog/images/<path:subpath>', type='http', auth='user')
    def portal_catalog_asset(self, subpath, **kw):
        if (subpath.startswith('/') or '..' in subpath.split('/')
                or os.path.splitext(subpath)[1].lower() not in {
                    '.jpg', '.jpeg', '.png', '.webp', '.gif', '.svg', '.pdf',
                }):
            return request.not_found()
        try:
            base = os.path.realpath(file_path('rms_portal_catalog/catalog_private/images'))
            path = os.path.realpath(os.path.join(base, subpath))
            if os.path.commonpath([base, path]) != base:
                return request.not_found()
            with open(path, 'rb') as f:
                content = f.read()
        except (OSError, ValueError):
            return request.not_found()
        mimetype, _ = mimetypes.guess_type(subpath)
        return request.make_response(
            content,
            headers=[('Content-Type', mimetype or 'application/octet-stream'),
                     ('Cache-Control', 'private, max-age=86400'),
                     ('X-Content-Type-Options', 'nosniff')],
        )
