import json
import re
from datetime import timedelta

from odoo import fields, http
from odoo.http import request
from odoo.addons.rms_portal_catalog.controllers.portal import catalog_metadata

from odoo.addons.rms_portal_profiles.controllers.portal_guards import (
    AddressesProfileGuard,
    CatalogProfileGuard,
    InstallationProjectsProfileGuard,
    InvoicesProfileGuard,
    ProjectProfileGuard,
    SaleOrdersProfileGuard,
)

# Eventos que el catálogo estático (navegación en el navegador) puede enviar.
CLIENT_EVENT_TYPES = ('brand', 'card', 'prices', 'search')
CLIENT_EVENTS_PER_HOUR = 120
PAGE_KEY_RE = re.compile(r'[0-9A-Za-z_-]{1,32}')


def _ok(response):
    """True si la pantalla se ha servido (no es una redirección por falta de permisos)."""
    return getattr(response, 'status_code', 200) == 200


def _log(activity_type, **vals):
    vals.setdefault('url', request.httprequest.path)
    request.env['rms.portal.activity']._log(activity_type, **vals)


def _clean(value, size=200):
    return (value or '').strip()[:size] or False


class PortalActivityTrack(http.Controller):

    @http.route('/my/portal/track', type='http', auth='user', methods=['POST'])
    def portal_activity_track(self, **kw):
        def done():
            return request.make_response('', status=204)

        user = request.env.user
        activity_type = kw.get('kind')
        if (not user.share or user._is_public() or user.has_group('base.group_user')
                or not user.has_group('rms_portal_profiles.group_portal_customer')
                or activity_type not in CLIENT_EVENT_TYPES):
            return done()

        Activity = request.env['rms.portal.activity']
        if Activity.sudo().search_count([
            '|', ('user_id', '=', user.id), ('partner_id', '=', user.partner_id.id),
            ('create_date', '>', fields.Datetime.now() - timedelta(hours=1)),
        ], limit=CLIENT_EVENTS_PER_HOUR) >= CLIENT_EVENTS_PER_HOUR:
            return done()

        # Ignore unrelated client fields so they cannot alter deduplication.
        vals = {}
        if activity_type == 'search':
            query = (kw.get('query') or '').strip()
            results = kw.get('results', '')
            if not query or len(query) > 100 or not re.fullmatch(r'[0-9]{1,5}', results):
                return done()
            count = int(results)
            if count > 10000:
                return done()
            vals.update(name=query, result_count=count, url='/my/catalog')
        else:
            pages, brands = catalog_metadata()
            Card = request.env['rms.catalog.card'].sudo()
            if activity_type in ('card', 'prices'):
                key = kw.get('key') or ''
                if not PAGE_KEY_RE.fullmatch(key):
                    return done()
                card = Card.search([('page_key', '=', key)], limit=1)
                if pages and brands:
                    if key not in pages:
                        return done()
                    title = card.title or pages[key]['title']
                    brand = brands[pages[key]['brand']]['name']
                else:
                    if not card:
                        return done()
                    title = card.title or ''
                    brand = card.brand or ''
                vals.update(page_key=key, card_id=card.id or False, page_title=title,
                            name=title, url='/my/catalog#view/' + key)
            else:
                title = ''
                brand = (kw.get('brand') or '').strip()
                if pages and brands:
                    brand = next((data['name'] for key, data in brands.items()
                                  if brand in (key, data['name'])), '')
                vals.update(name=brand, url='/my/catalog')
            if len(title) > 120 or len(brand) > 64:
                return done()
            if not (pages and brands):
                known_brands = Card.search([('brand', '!=', False)]).mapped('brand')
                if brand and brand not in known_brands:
                    return done()
            if activity_type == 'brand' and not brand:
                return done()
            vals['brand'] = brand or False
        Activity._log(activity_type, **vals)
        return done()


class SaleOrdersActivity(SaleOrdersProfileGuard):

    @http.route()
    def portal_my_quotes(self, **kwargs):
        res = super().portal_my_quotes(**kwargs)
        if _ok(res):
            _log('portal_page', name='Mis presupuestos')
        return res

    @http.route()
    def portal_my_orders(self, **kwargs):
        res = super().portal_my_orders(**kwargs)
        if _ok(res):
            _log('portal_page', name='Mis pedidos')
        return res

    @http.route()
    def portal_order_page(self, order_id, **kw):
        res = super().portal_order_page(order_id, **kw)
        if _ok(res):
            order = request.env['sale.order'].sudo().browse(int(order_id)).exists()
            if order:
                detail = order.name
                if kw.get('report_type') == 'pdf':
                    detail += ' (PDF)'
                _log('sale_order', sale_order_id=order.id, name=detail)
        return res


class InvoicesActivity(InvoicesProfileGuard):

    @http.route()
    def portal_my_invoices(self, page=1, date_begin=None, date_end=None, sortby=None, filterby=None, **kw):
        res = super().portal_my_invoices(
            page=page, date_begin=date_begin, date_end=date_end, sortby=sortby, filterby=filterby, **kw
        )
        if _ok(res):
            _log('portal_page', name='Mis facturas')
        return res

    @http.route()
    def portal_my_invoice_detail(self, invoice_id, **kw):
        res = super().portal_my_invoice_detail(invoice_id, **kw)
        if _ok(res):
            invoice = request.env['account.move'].sudo().browse(int(invoice_id)).exists()
            if invoice:
                detail = invoice.name
                if kw.get('report_type') == 'pdf':
                    detail += ' (PDF)'
                _log('invoice', invoice_id=invoice.id, name=detail)
        return res


class HomeActivity(AddressesProfileGuard):

    @http.route()
    def home(self, **kw):
        res = super().home(**kw)
        if _ok(res):
            _log('portal_page', name='Inicio del portal')
        return res

    @http.route()
    def my_addresses(self, **query_params):
        res = super().my_addresses(**query_params)
        if _ok(res):
            _log('portal_page', name='Mis direcciones')
        return res


class ProjectActivity(ProjectProfileGuard):

    @http.route()
    def portal_my_projects(self, page=1, date_begin=None, date_end=None, sortby=None, **kw):
        res = super().portal_my_projects(page=page, date_begin=date_begin, date_end=date_end, sortby=sortby, **kw)
        if _ok(res):
            _log('portal_page', name='Proyectos de marketing')
        return res

    @http.route()
    def portal_my_tasks(self, page=1, date_begin=None, date_end=None, sortby=None, filterby=None,
                        search=None, search_in='name', groupby=None, **kw):
        res = super().portal_my_tasks(
            page=page, date_begin=date_begin, date_end=date_end, sortby=sortby, filterby=filterby,
            search=search, search_in=search_in, groupby=groupby, **kw
        )
        if _ok(res):
            _log('portal_page', name='Tareas de marketing')
        return res


class InstallationProjectsActivity(InstallationProjectsProfileGuard):

    @http.route()
    def portal_my_installation_projects(self, page=1, sortby=None, **kw):
        res = super().portal_my_installation_projects(page=page, sortby=sortby, **kw)
        if _ok(res):
            _log('portal_page', name='Proyectos de instalación')
        return res

    @http.route()
    def portal_installation_project_detail(self, project_id, **kw):
        res = super().portal_installation_project_detail(project_id, **kw)
        if _ok(res):
            self._log_installation_project(project_id)
        return res

    @http.route()
    def portal_installation_project_file(self, project_id, **kw):
        res = super().portal_installation_project_file(project_id, **kw)
        if _ok(res):
            self._log_installation_project(project_id)
        return res

    def _log_installation_project(self, project_id):
        project = request.env['rms.installation.project'].sudo().browse(int(project_id)).exists()
        if project:
            _log('project', project_id=project.id, name=project.display_name)


class CatalogActivity(CatalogProfileGuard):

    @http.route()
    def portal_catalog_home(self, **kw):
        res = super().portal_catalog_home(**kw)
        if _ok(res):
            _log('catalog_home', name='Catálogo')
        return res

    @http.route()
    def portal_catalog_quote_add(self, product_id, **kw):
        res = super().portal_catalog_quote_add(product_id, **kw)
        if _ok(res) and self._quote_response_ok(res):
            template = request.env['product.template'].sudo().browse(int(product_id)).exists()
            if template:
                card = request.env['rms.catalog.card.line'].sudo().search(
                    [('product_id.product_tmpl_id', '=', template.id)], limit=1,
                ).card_id
                _log(
                    'quote_add',
                    product_tmpl_id=template.id,
                    name=template.display_name,
                    card_id=card.id or False,
                    page_key=card.page_key or False,
                    page_title=card.title or False,
                    brand=card.brand or False,
                )
        return res

    @http.route()
    def portal_catalog_quote_pdf(self, **kw):
        res = super().portal_catalog_quote_pdf(**kw)
        if _ok(res):
            order = self._get_portal_cart()
            _log('quote_pdf', sale_order_id=order.id or False, name=order.name or 'Presupuesto')
        return res

    @http.route()
    def portal_catalog_brand_pdf(self, brand, **kw):
        res = super().portal_catalog_brand_pdf(brand, **kw)
        if _ok(res):
            brand_name = _clean(kw.get('name'), 64) or brand
            _log('catalog_pdf', brand=brand_name, name='Catálogo %s' % brand_name)
        return res

    @staticmethod
    def _quote_response_ok(res):
        try:
            return json.loads(res.get_data()).get('ok', True)
        except (ValueError, AttributeError):
            return True
