import base64
import re

from odoo import http
from odoo.exceptions import AccessError, MissingError
from odoo.http import content_disposition, request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager

BACK_TO_PORTAL_BUTTON = b"""
<a href="/my" style="position:fixed;top:12px;right:12px;z-index:2147483647;display:inline-flex;
align-items:center;gap:6px;padding:8px 14px;background:#1d1d1f;color:#fff;
font:600 13px/1.2 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;border-radius:999px;
text-decoration:none;box-shadow:0 4px 14px rgba(0,0,0,.25);">&#8592; Volver al portal</a>
"""


class InstallationProjectPortal(CustomerPortal):

    def _installation_project_domain(self):
        partner = request.env.user.partner_id
        return [
            ('partner_id', '=', partner.id),
            ('state', '!=', 'draft'),
        ]

    def _can_read_installation_projects(self):
        user = request.env.user
        return user.has_group('base.group_portal') or user.has_group(
            'rms_portal_projects.group_installation_project_manager'
        )

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'installation_project_count' in counters:
            values['installation_project_count'] = request.env['rms.installation.project'].search_count(
                self._installation_project_domain()
            ) if self._can_read_installation_projects() else 0
        return values

    def _prepare_portal_layout_values(self):
        values = super()._prepare_portal_layout_values()
        values['installation_project_count'] = request.env['rms.installation.project'].search_count(
            self._installation_project_domain()
        ) if self._can_read_installation_projects() else 0
        return values

    def _installation_project_check_access(self, project_id):
        project = request.env['rms.installation.project'].browse([project_id])
        project_sudo = project.sudo().exists()
        if not project_sudo:
            raise MissingError('No document found.')
        partner = request.env.user.partner_id
        if project_sudo.partner_id != partner or project_sudo.state == 'draft':
            raise AccessError('Access denied.')
        return project_sudo

    @http.route(['/my/installation-projects', '/my/installation-projects/page/<int:page>'], type='http', auth='user', website=True)
    def portal_my_installation_projects(self, page=1, sortby=None, **kw):
        Project = request.env['rms.installation.project']
        domain = self._installation_project_domain()

        searchbar_sortings = {
            'date': {'label': 'Fecha', 'order': 'date desc'},
            'name': {'label': 'Referencia', 'order': 'name'},
        }
        sortby = sortby or 'date'
        order = searchbar_sortings[sortby]['order']

        project_count = Project.search_count(domain)
        pager = portal_pager(
            url='/my/installation-projects',
            url_args={'sortby': sortby},
            total=project_count,
            page=page,
            step=self._items_per_page,
        )
        projects = Project.search(domain, order=order, limit=self._items_per_page, offset=pager['offset'])

        values = {
            'projects': projects,
            'page_name': 'installation_project',
            'pager': pager,
            'default_url': '/my/installation-projects',
            'searchbar_sortings': searchbar_sortings,
            'sortby': sortby,
        }
        return request.render('rms_portal_projects.portal_my_installation_projects', values)

    @http.route(['/my/installation-projects/<int:project_id>'], type='http', auth='user', website=True)
    def portal_installation_project_detail(self, project_id, **kw):
        try:
            project_sudo = self._installation_project_check_access(project_id)
        except (AccessError, MissingError):
            return request.redirect('/my')

        if project_sudo.file_data:
            return request.redirect('/my/installation-projects/%s/file' % project_id)

        values = {
            'page_name': 'installation_project',
            'project': project_sudo,
        }
        return request.render('rms_portal_projects.portal_installation_project_page', values)

    @http.route(['/my/installation-projects/<int:project_id>/file'], type='http', auth='user')
    def portal_installation_project_file(self, project_id, **kw):
        try:
            project_sudo = self._installation_project_check_access(project_id)
        except (AccessError, MissingError):
            return request.redirect('/my')

        if not project_sudo.file_data:
            return request.redirect('/my/installation-projects/%s' % project_id)

        document = base64.b64decode(project_sudo.file_data)
        insertion = re.search(br'<body\b[^>]*>', document, re.IGNORECASE)
        if insertion is None:
            insertion = re.search(br'</head\s*>', document, re.IGNORECASE)
        offset = insertion.end() if insertion else 0
        document = document[:offset] + BACK_TO_PORTAL_BUTTON + document[offset:]

        return request.make_response(
            document,
            headers=[
                ('Content-Type', 'text/html; charset=utf-8'),
                ('Content-Disposition', content_disposition(
                    project_sudo.file_name or 'proyecto.html', disposition_type='inline',
                )),
                ('Content-Security-Policy', 'sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox allow-downloads'),
                ('X-Content-Type-Options', 'nosniff'),
                ('Referrer-Policy', 'no-referrer'),
                ('Cache-Control', 'private, no-store'),
            ],
        )
