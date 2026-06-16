import base64
import html
import io
import re

from odoo import _, api, fields, models
from odoo.exceptions import AccessError


class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    def _default_knowledge_category_id(self):
        return self.env.ref(
            'rms_custom_knowledge.document_knowledge_category_general',
            raise_if_not_found=False,
        )

    is_knowledge_document = fields.Boolean(
        string='Knowledge Document',
        index=True,
        default=False,
    )
    knowledge_category_id = fields.Many2one(
        'document.knowledge.category',
        string='Directory',
        index=True,
        ondelete='restrict',
        default=_default_knowledge_category_id,
    )
    body_markdown = fields.Text(
        string='Markdown Content',
        readonly=True,
        copy=False,
    )
    body_html = fields.Html(
        string='Preview',
        compute='_compute_body_html',
        sanitize=False,
    )
    preview_url = fields.Char(
        string='Preview URL',
        compute='_compute_preview_url',
    )
    last_upload_date_display = fields.Char(
        string='Fecha de ultima subida',
        compute='_compute_last_upload_date_display',
    )

    @api.depends('write_date')
    def _compute_last_upload_date_display(self):
        for attachment in self:
            if not attachment.write_date:
                attachment.last_upload_date_display = False
                continue
            date_value = fields.Datetime.context_timestamp(attachment, attachment.write_date)
            attachment.last_upload_date_display = date_value.strftime('%d/%m/%Y %H:%M:%S')

    def _check_knowledge_manager_access(self):
        if not self.env.user.has_group('rms_custom_knowledge.group_knowledge_manager'):
            raise AccessError(_('Only Knowledge Managers can manage knowledge documents.'))

    @api.depends('datas', 'mimetype', 'name', 'is_knowledge_document')
    def _compute_body_html(self):
        for attachment in self:
            attachment.body_html = attachment._get_knowledge_preview_html()

    @api.depends('datas', 'mimetype', 'name', 'is_knowledge_document')
    def _compute_preview_url(self):
        for attachment in self:
            attachment.preview_url = attachment._get_knowledge_preview_url()

    @api.model_create_multi
    def create(self, vals_list):
        if any(vals.get('is_knowledge_document') for vals in vals_list):
            self._check_knowledge_manager_access()
        for vals in vals_list:
            if vals.get('is_knowledge_document'):
                vals['body_markdown'] = False
        return super().create(vals_list)

    def write(self, vals):
        touches_knowledge_document = vals.get('is_knowledge_document') or any(self.mapped('is_knowledge_document'))
        if touches_knowledge_document:
            self._check_knowledge_manager_access()
        if vals.get('datas') and touches_knowledge_document:
            vals = dict(vals)
            vals['body_markdown'] = False
            self._unlink_html_preview_attachments()
        return super().write(vals)

    def unlink(self):
        if any(self.mapped('is_knowledge_document')):
            self._check_knowledge_manager_access()
            self._unlink_html_preview_attachments()
        return super().unlink()

    def _get_knowledge_preview_url(self):
        self.ensure_one()
        if not self.datas or not self.id:
            return False

        mimetype = self.mimetype or ''
        filename = (self.name or '').lower()
        if self._is_textual_preview_file(mimetype, filename) or self._is_excel_file(mimetype, filename):
            return False
        if mimetype.startswith('image/'):
            return '/web/image/ir.attachment/%s/datas' % self.id
        return '/web/content/%s?download=false' % self.id

    def _get_knowledge_preview_html(self):
        self.ensure_one()
        if not self.datas:
            return self._preview_empty_html(_("Upload a file to preview it here."))
        if not self.id:
            return self._preview_empty_html(_("Save the document to generate the preview."))

        mimetype = self.mimetype or ""
        filename = (self.name or "").lower()
        title = html.escape(self.name or _("Document"))
        if self._is_excel_file(mimetype, filename):
            return self._wrap_preview_inline_html(self._get_excel_preview_body())
        if self._is_textual_preview_file(mimetype, filename):
            return self._wrap_preview_inline_html(self._get_textual_preview_body())

        preview_url = self._get_knowledge_preview_url()
        if not preview_url:
            return self._preview_empty_html(_("No preview available."))
        return self._iframe_preview(preview_url, title)

    def _get_or_create_html_preview_attachment(self):
        self.ensure_one()
        preview = self.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'ir.attachment'),
            ('res_id', '=', self.id),
            ('res_field', '=', 'rms_knowledge_preview'),
        ], limit=1)
        html_document = self._wrap_preview_html_document(self._get_textual_preview_body())
        values = {
            'name': '%s.preview.html' % (self.name or self.id),
            'type': 'binary',
            'datas': base64.b64encode(html_document.encode()).decode(),
            'mimetype': 'text/html',
            'res_model': 'ir.attachment',
            'res_id': self.id,
            'res_field': 'rms_knowledge_preview',
        }
        if preview:
            preview.write(values)
        else:
            preview = self.env['ir.attachment'].sudo().create(values)
        return preview

    def _unlink_html_preview_attachments(self):
        previews = self.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'ir.attachment'),
            ('res_id', 'in', self.ids),
            ('res_field', '=', 'rms_knowledge_preview'),
        ])
        previews.unlink()

    def _get_textual_preview_body(self):
        self.ensure_one()
        mimetype = self.mimetype or ''
        filename = (self.name or '').lower()
        if self._is_markdown_file(mimetype, filename):
            return self._markdown_to_html(self._decode_datas_as_text())
        return '<pre style="white-space: pre-wrap; word-break: break-word;">%s</pre>' % html.escape(
            self._decode_datas_as_text()
        )

    def _get_excel_preview_body(self):
        self.ensure_one()
        mimetype = self.mimetype or ""
        filename = (self.name or "").lower()
        if not self._is_modern_excel_file(mimetype, filename):
            return self._preview_empty_html(_("Excel .xls preview is not supported. Please upload an .xlsx file."))

        try:
            from openpyxl import load_workbook
            from openpyxl.utils import get_column_letter, range_boundaries
        except ImportError:
            return self._preview_empty_html(_("Install openpyxl to preview Excel files."))

        raw_content = self._get_raw_content()
        if not raw_content:
            return self._preview_empty_html(_("No readable content found in this file."))

        try:
            workbook = load_workbook(io.BytesIO(raw_content), read_only=False, data_only=True)
        except Exception:
            return self._preview_empty_html(_("This Excel file could not be previewed."))

        try:
            sheet = workbook.active
            max_rows = min(sheet.max_row or 1, 120)
            max_cols = min(sheet.max_column or 1, 40)
            table_ranges = self._get_excel_table_ranges(sheet, range_boundaries)
            rows = []
            colgroup = []
            for col_idx in range(1, max_cols + 1):
                width = sheet.column_dimensions[get_column_letter(col_idx)].width or 10
                colgroup.append('<col style="width: %spx;"/>' % int(max(42, min(width * 8, 260))))

            for row_idx in range(1, max_rows + 1):
                row_cells = []
                row_height = sheet.row_dimensions[row_idx].height
                row_style = 'height: %spx;' % int(row_height * 1.35) if row_height else ''
                for col_idx in range(1, max_cols + 1):
                    cell = sheet.cell(row=row_idx, column=col_idx)
                    table_style = self._get_excel_table_cell_style(row_idx, col_idx, table_ranges)
                    cell_style = self._get_excel_cell_style(cell, table_style)
                    row_cells.append(
                        '<td style="%s">%s</td>' % (
                            html.escape(cell_style, quote=True),
                            html.escape(self._format_excel_cell(cell.value)),
                        )
                    )
                rows.append('<tr style="%s">%s</tr>' % (html.escape(row_style, quote=True), ''.join(row_cells)))
        finally:
            workbook.close()

        if not rows:
            return self._preview_empty_html(_("No readable content found in this file."))

        note = _("Showing first %(rows)s rows and %(cols)s columns of sheet %(sheet)s.") % {
            "rows": max_rows,
            "cols": max_cols,
            "sheet": sheet.title,
        }
        return """<div class="o_rms_knowledge_excel_preview">
            <div class="text-muted" style="margin-bottom: 8px;">%s</div>
            <div style="overflow: auto; max-height: 72vh; background: white;">
                <table style="border-collapse: collapse; table-layout: fixed; width: max-content;">%s%s</table>
            </div>
        </div>""" % (html.escape(note), ''.join(colgroup), ''.join(rows))

    @api.model
    def _get_excel_table_ranges(self, sheet, range_boundaries):
        table_ranges = []
        for table in sheet.tables.values():
            min_col, min_row, max_col, max_row = range_boundaries(table.ref)
            table_ranges.append({
                'min_col': min_col,
                'min_row': min_row,
                'max_col': max_col,
                'max_row': max_row,
                'show_row_stripes': bool(table.tableStyleInfo and table.tableStyleInfo.showRowStripes),
            })
        return table_ranges

    @api.model
    def _get_excel_table_cell_style(self, row_idx, col_idx, table_ranges):
        for table_range in table_ranges:
            if not (
                table_range['min_row'] <= row_idx <= table_range['max_row']
                and table_range['min_col'] <= col_idx <= table_range['max_col']
            ):
                continue
            if row_idx == table_range['min_row']:
                return {
                    'background': '#0070c0',
                    'color': '#ffffff',
                    'bold': True,
                    'border': '#ffffff',
                }
            if table_range['show_row_stripes'] and (row_idx - table_range['min_row']) % 2 == 1:
                return {'background': '#cfe8f7', 'border': '#00a2e8'}
            return {'background': '#ffffff', 'border': '#00a2e8'}
        return {}

    @api.model
    def _get_excel_cell_style(self, cell, table_style=None):
        table_style = table_style or {}
        styles = [
            'border: 1px solid %s' % table_style.get('border', '#d9e2ec'),
            'padding: 3px 6px',
            'white-space: nowrap',
            'overflow: hidden',
            'text-overflow: ellipsis',
            'height: 22px',
            'font-size: 13px',
            'vertical-align: middle',
        ]
        background = table_style.get('background') or self._excel_color_to_css(cell.fill.fgColor)
        if background:
            styles.append('background-color: %s' % background)
        color = table_style.get('color') or self._excel_color_to_css(cell.font.color)
        if color:
            styles.append('color: %s' % color)
        if cell.font.bold or table_style.get('bold'):
            styles.append('font-weight: 700')
        if cell.font.italic:
            styles.append('font-style: italic')
        if cell.alignment.horizontal:
            styles.append('text-align: %s' % self._excel_horizontal_alignment(cell.alignment.horizontal))
        if cell.alignment.vertical:
            styles.append('vertical-align: %s' % self._excel_vertical_alignment(cell.alignment.vertical))
        return '; '.join(styles) + ';'

    @api.model
    def _excel_color_to_css(self, color):
        if not color or color.type != 'rgb' or not color.rgb:
            return False
        rgb = color.rgb[-6:]
        if rgb.upper() in ('000000', 'FFFFFF'):
            return False
        return '#%s' % rgb

    @api.model
    def _excel_horizontal_alignment(self, value):
        return {
            'center': 'center',
            'right': 'right',
            'fill': 'left',
            'justify': 'justify',
            'centerContinuous': 'center',
            'distributed': 'justify',
        }.get(value, 'left')

    @api.model
    def _excel_vertical_alignment(self, value):
        return {
            'top': 'top',
            'center': 'middle',
            'bottom': 'bottom',
            'justify': 'middle',
            'distributed': 'middle',
        }.get(value, 'middle')

    @api.model
    def _format_excel_cell(self, value):
        if value is None:
            return ""
        if hasattr(value, "isoformat"):
            try:
                return value.isoformat(sep=" ")
            except TypeError:
                return value.isoformat()
        return str(value)

    @api.model
    def _wrap_preview_inline_html(self, body):
        if not body:
            return self._preview_empty_html(_("No readable content found in this file."))
        return """<div class="o_rms_knowledge_preview o_rms_knowledge_markdown_preview" style="padding: 24px; line-height: 1.55;">%s</div>""" % body

    @api.model
    def _wrap_preview_html_document(self, body):
        return """<!doctype html>
<html>
<head>
<meta charset="utf-8"/>
<style>
body { font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 24px; color: #111827; line-height: 1.55; }
a { color: #714b9f; }
pre { background: #f8fafc; border: 1px solid #e5e7eb; border-radius: 6px; padding: 16px; overflow: auto; }
code { background: #f3f4f6; border-radius: 4px; padding: 1px 4px; }
blockquote { border-left: 4px solid #d1d5db; margin-left: 0; padding-left: 16px; color: #4b5563; }
img { max-width: 100%%; height: auto; }
table { border-collapse: collapse; width: 100%%; }
th, td { border: 1px solid #d1d5db; padding: 6px 8px; }
</style>
</head>
<body>%s</body>
</html>""" % body

    @api.model
    def _preview_empty_html(self, message):
        return '<div class="text-muted">%s</div>' % html.escape(message)

    @api.model
    def _iframe_preview(self, url, title):
        return """<div class="o_rms_knowledge_preview o_rms_knowledge_preview_iframe">
            <iframe src="%s" title="%s" style="width: 100%%; min-height: 72vh; border: 0;"></iframe>
        </div>""" % (url, title)

    @api.model
    def _iframe_srcdoc_preview(self, html_document, title):
        return """<div class="o_rms_knowledge_preview o_rms_knowledge_preview_iframe">
            <iframe srcdoc="%s" title="%s" sandbox="allow-popups allow-popups-to-escape-sandbox" style="width: 100%%; min-height: 72vh; border: 0;"></iframe>
        </div>""" % (html.escape(html_document, quote=True), title)

    @api.model
    def _is_excel_file(self, mimetype, filename):
        return mimetype in (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.ms-excel.sheet.macroEnabled.12",
            "application/vnd.ms-excel",
        ) or filename.endswith((".xlsx", ".xlsm", ".xltx", ".xltm", ".xls"))

    @api.model
    def _is_modern_excel_file(self, mimetype, filename):
        return mimetype in (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.ms-excel.sheet.macroEnabled.12",
        ) or filename.endswith((".xlsx", ".xlsm", ".xltx", ".xltm"))

    @api.model
    def _is_markdown_file(self, mimetype, filename):
        return mimetype in ('text/markdown', 'text/x-markdown') or filename.endswith(('.md', '.markdown'))

    @api.model
    def _is_textual_preview_file(self, mimetype, filename):
        return (
            self._is_markdown_file(mimetype, filename)
            or mimetype.startswith('text/')
            or mimetype in ('application/json', 'application/xml')
            or filename.endswith(('.txt', '.csv', '.log', '.rst', '.json', '.xml', '.yaml', '.yml'))
        )

    def _get_raw_content(self):
        self.ensure_one()
        if self.store_fname:
            return self._file_read(self.store_fname)
        return self.db_datas or b""

    def _decode_datas_as_text(self):
        self.ensure_one()
        raw_content = self._get_raw_content()

        if isinstance(raw_content, str):
            raw_content = raw_content.encode()

        for encoding in ("utf-8", "latin-1"):
            try:
                return raw_content.decode(encoding)
            except UnicodeDecodeError:
                continue
        return raw_content.decode("utf-8", errors="replace")

    @api.model
    def _markdown_to_html(self, markdown_text):
        if not markdown_text:
            return ''

        try:
            import markdown
        except ImportError:
            return self._basic_markdown_to_html(markdown_text)

        return markdown.markdown(
            markdown_text,
            extensions=['extra', 'sane_lists', 'nl2br'],
            output_format='html5',
        )

    @api.model
    def _basic_markdown_to_html(self, markdown_text):
        blocks = []
        paragraph = []
        list_items = []

        def flush_paragraph():
            if paragraph:
                text = ' '.join(paragraph).strip()
                blocks.append('<p>%s</p>' % self._inline_markdown_to_html(text))
                paragraph.clear()

        def flush_list():
            if list_items:
                blocks.append('<ul>%s</ul>' % ''.join('<li>%s</li>' % item for item in list_items))
                list_items.clear()

        for raw_line in markdown_text.splitlines():
            line = raw_line.strip()
            if not line:
                flush_paragraph()
                flush_list()
                continue

            heading = re.match(r'^(#{1,6})\s+(.+)$', line)
            if heading:
                flush_paragraph()
                flush_list()
                level = len(heading.group(1))
                blocks.append('<h%s>%s</h%s>' % (level, self._inline_markdown_to_html(heading.group(2)), level))
                continue

            bullet = re.match(r'^[-*+]\s+(.+)$', line)
            if bullet:
                flush_paragraph()
                list_items.append(self._inline_markdown_to_html(bullet.group(1)))
                continue

            flush_list()
            paragraph.append(line)

        flush_paragraph()
        flush_list()
        return '<div class="o_rms_knowledge_markdown">%s</div>' % ''.join(blocks)

    @api.model
    def _inline_markdown_to_html(self, text):
        escaped = html.escape(text)
        escaped = re.sub(r'`([^`]+)`', r'<code>\1</code>', escaped)
        escaped = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', escaped)
        escaped = re.sub(r'__([^_]+)__', r'<strong>\1</strong>', escaped)
        escaped = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'<em>\1</em>', escaped)
        escaped = re.sub(r'\[([^\]]+)\]\((https?://[^)]+)\)', r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>', escaped)
        return escaped
