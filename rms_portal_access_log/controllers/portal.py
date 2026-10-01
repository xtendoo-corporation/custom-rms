import json

from odoo import http
from odoo.http import request

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


def _ok(response):
    """True si la pantalla se ha servido (no es una redirección por falta de permisos)."""
    return getattr(response, 'status_code', 200) == 200


def _log(activity_type, **vals):
    vals.setdefault('url', request.httprequest.path)
    request.env['rms.portal.activity']._log(activity_type, **vals)


def _clean(value, size=200):
    return (value or '').strip()[:size] or False


class PortalActivityTrack(http.Controller):

    @http.route('/my/portal/track', type='http', auth='user', methods=['POST'], csrf=False)
    def portal_activity_track(self, **kw):
        activity_type = kw.get('kind')
        if activity_type in CLIENT_EVENT_TYPES:
            vals = {
                'page_key': _clean(kw.get('key'), 64),
                'page_title': _clean(kw.get('title')),
                'brand': _clean(kw.get('brand'), 64),
                'url': '/my/catalog#' + (_clean(kw.get('hash'), 200) or ''),
            }
            if activity_type == 'search':
                vals['page_key'] = False
                vals['name'] = _clean(kw.get('query'), 100)
                try:
                    vals['result_count'] = int(kw.get('results') or 0)
                except ValueError:
                    vals['result_count'] = 0
                if not vals['name']:
                    return request.make_response('', status=204)
            elif activity_type == 'brand':
                vals['name'] = vals['brand']
                vals['page_key'] = False
            else:
                vals['name'] = vals['page_title']
            request.env['rms.portal.activity']._log(activity_type, **vals)
        return request.make_response('', status=204)


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
