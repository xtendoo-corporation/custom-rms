from odoo import api, fields, models
from odoo.osv import expression


class DocumentKnowledgeCategory(models.Model):
    _name = 'document.knowledge.category'
    _description = 'Document Knowledge Directory'
    _parent_name = 'parent_id'
    _parent_store = True
    _rec_name = 'complete_name'
    _order = 'complete_name, id'

    name = fields.Char(required=True, translate=True)
    cover_image = fields.Image(
        string='Imagen de portada',
        max_width=1920,
        max_height=1080,
        attachment=True,
    )
    icon = fields.Char(
        string='Icono',
        default='📁',
        help=(
            'Emoji o carácter corto utilizado para identificar visualmente '
            'el directorio.'
        ),
    )
    complete_name = fields.Char(
        compute='_compute_complete_name',
        recursive=True,
        store=True,
    )
    parent_id = fields.Many2one(
        'document.knowledge.category',
        string='Parent Directory',
        index=True,
        ondelete='cascade',
    )
    parent_path = fields.Char(index=True)
    child_ids = fields.One2many(
        'document.knowledge.category',
        'parent_id',
        string='Subdirectories',
    )
    attachment_ids = fields.One2many(
        'ir.attachment',
        'knowledge_category_id',
        string='Documents',
    )
    access_line_ids = fields.One2many(
        'document.knowledge.access',
        'category_id',
        string='Permisos por usuario',
    )
    user_can_upload_here = fields.Boolean(
        string='Puede subir aqui',
        compute='_compute_user_can_upload_here',
    )
    description = fields.Text(translate=True)
    document_count = fields.Integer(compute='_compute_document_count')

    @api.depends('name', 'parent_id.complete_name')
    def _compute_complete_name(self):
        for category in self:
            if category.parent_id:
                category.complete_name = '%s / %s' % (
                    category.parent_id.complete_name,
                    category.name,
                )
            else:
                category.complete_name = category.name

    def _compute_document_count(self):
        grouped = self.env['ir.attachment']._read_group(
            [('knowledge_category_id', 'in', self.ids)],
            ['knowledge_category_id'],
            ['__count'],
        )
        counts = {category.id: count for category, count in grouped}
        for category in self:
            category.document_count = counts.get(category.id, 0)

    @api.model
    def _get_user_readable_category_ids(self):
        if (
            self.env.user.has_group('rms_custom_knowledge.group_knowledge_manager')
            or self.env.user.has_group('rms_custom_knowledge.group_knowledge_contributor')
        ):
            return self.sudo().search([]).ids
        return self.env['document.knowledge.access'].sudo().search([
            ('user_id', '=', self.env.uid),
        ]).mapped('category_id').ids

    @api.model
    def _get_user_readable_category_domain(self):
        if (
            self.env.user.has_group('rms_custom_knowledge.group_knowledge_manager')
            or self.env.user.has_group('rms_custom_knowledge.group_knowledge_contributor')
        ):
            return []

        category_ids = self.env['document.knowledge.access'].sudo().search([
            ('user_id', '=', self.env.uid),
        ]).mapped('category_id').ids
        if not category_ids:
            return [('id', '=', 0)]
        return [('id', 'in', category_ids)]

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None, *, active_test=True, bypass_access=False):
        if not self.env.su and not bypass_access:
            domain = expression.AND([domain, self._get_user_readable_category_domain()])
            return super()._search(
                domain,
                offset=offset,
                limit=limit,
                order=order,
                active_test=active_test,
                bypass_access=True,
            )
        return super()._search(
            domain,
            offset=offset,
            limit=limit,
            order=order,
            active_test=active_test,
            bypass_access=bypass_access,
        )

    @api.depends_context('uid')
    def _compute_user_can_upload_here(self):
        uploadable_category_ids = self._get_user_uploadable_category_ids(self.ids)
        for category in self:
            category.user_can_upload_here = category.id in uploadable_category_ids

    @api.model
    def _get_user_uploadable_category_ids(self, category_ids=None):
        if (
            self.env.user.has_group('rms_custom_knowledge.group_knowledge_manager')
            or self.env.user.has_group('rms_custom_knowledge.group_knowledge_contributor')
        ):
            if category_ids is None:
                return set(self.search([]).ids)
            return set(category_ids)

        domain = [
            ('user_id', '=', self.env.uid),
            ('permission', '=', 'read_upload'),
        ]
        if category_ids is not None:
            domain.append(('category_id', 'in', category_ids))

        return set(
            self.env['document.knowledge.access'].sudo().search(domain).mapped('category_id').ids
        )

    def _check_user_can_upload_here(self):
        self.ensure_one()
        if (
            self.env.user.has_group('rms_custom_knowledge.group_knowledge_manager')
            or self.env.user.has_group('rms_custom_knowledge.group_knowledge_contributor')
        ):
            return True
        if not self.id:
            return False
        return bool(self.env['document.knowledge.access'].sudo().search_count([
            ('category_id', '=', self.id),
            ('user_id', '=', self.env.uid),
            ('permission', '=', 'read_upload'),
        ]))

    def action_open_knowledge_category(self):
        if not self:
            return False
        self.ensure_one()
        form_view = self.env.ref(
            'rms_custom_knowledge.view_document_knowledge_category_form'
        )
        return {
            'type': 'ir.actions.act_window',
            'name': self.display_name,
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(form_view.id, 'form')],
            'target': 'current',
        }

    def action_create_knowledge_subdirectory(self):
        self.ensure_one()
        form_view = self.env.ref(
            'rms_custom_knowledge.view_document_knowledge_subdirectory_form'
        )
        return {
            'type': 'ir.actions.act_window',
            'name': 'Nueva carpeta',
            'res_model': self._name,
            'view_mode': 'form',
            'views': [(form_view.id, 'form')],
            'target': 'new',
            'context': {
                **self.env.context,
                'default_parent_id': self.id,
                'default_icon': '📁',
            },
        }
