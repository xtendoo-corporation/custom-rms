import base64
import json
import logging

import requests

from odoo import http
from odoo.exceptions import AccessError, UserError
from odoo.http import content_disposition, request

_logger = logging.getLogger(__name__)

try:
    import jwt as pyjwt
except ImportError:
    pyjwt = None


class OnlyOfficeController(http.Controller):

    @http.route('/rms_custom_knowledge/onlyoffice/editor/<int:attachment_id>', type='http', auth='user')
    def onlyoffice_editor(self, attachment_id, **kwargs):
        attachment = request.env['ir.attachment'].browse(attachment_id).exists()
        if not attachment:
            return request.not_found()

        try:
            editor_data = attachment.get_onlyoffice_editor_config()
        except (AccessError, UserError) as exc:
            return request.render('rms_custom_knowledge.onlyoffice_editor_error', {
                'message': str(exc),
            })

        return request.render('rms_custom_knowledge.onlyoffice_editor_page', {
            'server_url': editor_data['server_url'],
            'config_json': json.dumps(editor_data['config']),
            'title': attachment.name,
        })

    @http.route('/rms_custom_knowledge/onlyoffice/content/<int:attachment_id>', type='http', auth='public')
    def onlyoffice_content(self, attachment_id, token=None, **kwargs):
        IrAttachment = request.env['ir.attachment'].sudo()
        try:
            uid = IrAttachment._verify_onlyoffice_url_token(token, attachment_id, 'content')
        except Exception:
            return request.not_found()

        attachment = IrAttachment.browse(attachment_id).exists()
        if not attachment:
            return request.not_found()

        try:
            attachment.with_user(uid).check_access('read')
        except AccessError:
            return request.not_found()

        raw_content = attachment._get_raw_content()
        return request.make_response(
            raw_content,
            headers=[
                ('Content-Type', attachment.mimetype or 'application/octet-stream'),
                ('Content-Disposition', content_disposition(attachment.name or 'documento')),
            ],
        )

    @http.route('/rms_custom_knowledge/onlyoffice/callback/<int:attachment_id>', type='http', auth='public', csrf=False, methods=['POST'])
    def onlyoffice_callback(self, attachment_id, token=None, **kwargs):
        IrAttachment = request.env['ir.attachment'].sudo()
        try:
            uid = IrAttachment._verify_onlyoffice_url_token(token, attachment_id, 'callback')
        except Exception:
            return request.make_response(json.dumps({'error': 1, 'message': 'Invalid token'}), headers=[('Content-Type', 'application/json')])

        try:
            self._verify_onlyoffice_server_jwt()
        except AccessError:
            return request.make_response(json.dumps({'error': 1, 'message': 'Invalid server token'}), headers=[('Content-Type', 'application/json')])

        try:
            payload = json.loads(request.httprequest.data or b'{}')
        except ValueError:
            return request.make_response(json.dumps({'error': 1, 'message': 'Invalid payload'}), headers=[('Content-Type', 'application/json')])

        status = payload.get('status')
        if status in (2, 6) and payload.get('url'):
            attachment = IrAttachment.browse(attachment_id).exists()
            if attachment:
                try:
                    file_response = requests.get(payload['url'], timeout=30)
                    file_response.raise_for_status()
                    attachment.with_user(uid).write({
                        'datas': base64.b64encode(file_response.content).decode(),
                    })
                except Exception:
                    _logger.exception('No se pudo guardar el documento OnlyOffice para el adjunto %s', attachment_id)
                    return request.make_response(json.dumps({'error': 1}), headers=[('Content-Type', 'application/json')])

        return request.make_response(json.dumps({'error': 0}), headers=[('Content-Type', 'application/json')])

    def _verify_onlyoffice_server_jwt(self):
        jwt_secret = request.env['ir.config_parameter'].sudo().get_param('rms_custom_knowledge.onlyoffice_jwt_secret')
        if not jwt_secret or pyjwt is None:
            return
        auth_header = request.httprequest.headers.get('Authorization', '')
        server_token = auth_header[7:] if auth_header.startswith('Bearer ') else auth_header
        if not server_token:
            raise AccessError('Missing OnlyOffice JWT token')
        pyjwt.decode(server_token, jwt_secret, algorithms=['HS256'])
