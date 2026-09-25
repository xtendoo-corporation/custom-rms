from odoo import http
from odoo.http import request

from odoo.addons.account.controllers.portal import PortalAccount
from odoo.addons.portal.controllers.portal import CustomerPortal as PortalBaseCustomerPortal
from odoo.addons.project.controllers.portal import ProjectCustomerPortal
from odoo.addons.rms_portal_catalog.controllers.portal import B2BCatalogPortal
from odoo.addons.rms_portal_projects.controllers.portal import InstallationProjectPortal
from odoo.addons.sale.controllers.portal import CustomerPortal as SaleCustomerPortal


def _has_any_group(*group_xmlids):
    user = request.env.user
    return any(user.has_group(xmlid) for xmlid in group_xmlids)


def _is_internal_user():
    return request.env.user.has_group('base.group_user')


class SaleOrdersProfileGuard(SaleCustomerPortal):

    @http.route()
    def portal_my_quotes(self, **kwargs):
        if not _has_any_group('rms_portal_profiles.group_portal_customer'):
            return request.redirect('/my')
        return super().portal_my_quotes(**kwargs)

    @http.route()
    def portal_my_orders(self, **kwargs):
        if not _has_any_group('rms_portal_profiles.group_portal_customer'):
            return request.redirect('/my')
        return super().portal_my_orders(**kwargs)


class InvoicesProfileGuard(PortalAccount):

    @http.route()
    def portal_my_invoices(self, page=1, date_begin=None, date_end=None, sortby=None, filterby=None, **kw):
        if not _has_any_group('rms_portal_profiles.group_portal_customer'):
            return request.redirect('/my')
        return super().portal_my_invoices(
            page=page, date_begin=date_begin, date_end=date_end, sortby=sortby, filterby=filterby, **kw
        )


class AddressesProfileGuard(PortalBaseCustomerPortal):

    @http.route()
    def my_addresses(self, **query_params):
        if not _has_any_group('rms_portal_profiles.group_portal_customer'):
            return request.redirect('/my')
        return super().my_addresses(**query_params)


class ProjectProfileGuard(ProjectCustomerPortal):

    @http.route()
    def portal_my_projects(self, page=1, date_begin=None, date_end=None, sortby=None, **kw):
        if not _has_any_group('rms_portal_profiles.group_portal_marketing'):
            return request.redirect('/my')
        return super().portal_my_projects(page=page, date_begin=date_begin, date_end=date_end, sortby=sortby, **kw)

    @http.route()
    def portal_my_tasks(self, page=1, date_begin=None, date_end=None, sortby=None, filterby=None,
                         search=None, search_in='name', groupby=None, **kw):
        if not _has_any_group('rms_portal_profiles.group_portal_marketing'):
            return request.redirect('/my')
        return super().portal_my_tasks(
            page=page, date_begin=date_begin, date_end=date_end, sortby=sortby, filterby=filterby,
            search=search, search_in=search_in, groupby=groupby, **kw
        )


class InstallationProjectsProfileGuard(InstallationProjectPortal):

    @http.route()
    def portal_my_installation_projects(self, page=1, sortby=None, **kw):
        if not _has_any_group(
            'rms_portal_profiles.group_portal_customer',
            'rms_portal_profiles.group_portal_projects',
        ):
            return request.redirect('/my')
        return super().portal_my_installation_projects(page=page, sortby=sortby, **kw)


class CatalogProfileGuard(B2BCatalogPortal):

    @http.route()
    def portal_catalog_home(self, **kw):
        if not _is_internal_user() and not _has_any_group('rms_portal_profiles.group_portal_customer'):
            return request.redirect('/my')
        return super().portal_catalog_home(**kw)

    @http.route()
    def portal_catalog_asset(self, subpath, **kw):
        if not _is_internal_user() and not _has_any_group('rms_portal_profiles.group_portal_customer'):
            return request.redirect('/my')
        return super().portal_catalog_asset(subpath, **kw)

    @http.route()
    def portal_catalog_prices(self, category_ids, **kw):
        if not _is_internal_user() and not _has_any_group('rms_portal_profiles.group_portal_customer'):
            return request.redirect('/my')
        return super().portal_catalog_prices(category_ids, **kw)

    @http.route()
    def portal_catalog_product_image(self, product_id, **kw):
        if not _is_internal_user() and not _has_any_group('rms_portal_profiles.group_portal_customer'):
            return request.redirect('/my')
        return super().portal_catalog_product_image(product_id, **kw)

    @http.route()
    def portal_catalog_rep_photo(self, **kw):
        if not _is_internal_user() and not _has_any_group('rms_portal_profiles.group_portal_customer'):
            return request.redirect('/my')
        return super().portal_catalog_rep_photo(**kw)
