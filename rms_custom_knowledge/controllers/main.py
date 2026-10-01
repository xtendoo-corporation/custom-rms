import io
import zipfile

from odoo import http
from odoo.http import content_disposition, request


class KnowledgeDownloadController(http.Controller):

    @http.route('/rms_custom_knowledge/download', type='http', auth='user')
    def download_knowledge_documents(self, ids, **kwargs):
        attachment_ids = [int(attachment_id) for attachment_id in ids.split(',') if attachment_id.isdigit()]
        attachments = request.env['ir.attachment'].browse(attachment_ids).exists()
        downloadable = attachments.filtered(lambda attachment: attachment.type == 'binary' and attachment.datas)

        if not downloadable:
            return request.not_found()

        buffer = io.BytesIO()
        used_names = set()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            for attachment in downloadable:
                archive.writestr(self._get_unique_zip_name(attachment, used_names), attachment._get_raw_content())
        buffer.seek(0)

        return request.make_response(
            buffer.read(),
            headers=[
                ('Content-Type', 'application/zip'),
                ('Content-Disposition', content_disposition('documentos_conocimiento.zip')),
            ],
        )

    def _get_unique_zip_name(self, attachment, used_names):
        base_name = attachment.name or ('documento_%s' % attachment.id)
        candidate = base_name
        counter = 1
        stem, _, extension = base_name.rpartition('.')
        while candidate in used_names:
            candidate = '%s (%s).%s' % (stem, counter, extension) if extension else '%s (%s)' % (base_name, counter)
            counter += 1
        used_names.add(candidate)
        return candidate
