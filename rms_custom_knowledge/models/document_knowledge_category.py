from odoo import _, api, fields, models
from odoo.exceptions import AccessError
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
    def _get_user_permissions(self):
        # Admin / Knowledge Manager has full access
        is_manager = (
            self.env.user.has_group('rms_custom_knowledge.group_knowledge_manager')
            or self.env.user.has_group('base.group_system')
        )
        
        # Get all categories
        categories = self.sudo().search([])
        
        # Build parent-child relationships and map each category to its explicit access rules
        access_rules = self.env['document.knowledge.access'].sudo().search([])
        rules_by_category = {}
        for rule in access_rules:
            rules_by_category.setdefault(rule.category_id.id, []).append(rule)
            
        general_ref = self.env.ref('rms_custom_knowledge.document_knowledge_category_general', raise_if_not_found=False)
        general_id = general_ref.id if general_ref else None
        
        user_group_ids = set(self.env.user.all_group_ids.ids)
        
        permissions = {}
        
        def compute_perm(cat):
            if cat.id in permissions:
                return permissions[cat.id]
                
            if is_manager:
                permissions[cat.id] = 'delete'
                return 'delete'
                
            # Check explicit rules at this level
            rules = rules_by_category.get(cat.id, [])
            if rules:
                user_rules = [r for r in rules if r.group_id.id in user_group_ids]
                if user_rules:
                    # order: read < write < delete
                    perm_map = {'read': 1, 'write': 2, 'delete': 3}
                    max_perm = max(user_rules, key=lambda r: perm_map.get(r.permission, 0)).permission
                    permissions[cat.id] = max_perm
                    return max_perm
                else:
                    # Explicit rules exist but user is not in any of the groups
                    permissions[cat.id] = None
                    return None
                    
            # If no explicit rules, inherit from parent
            if cat.parent_id:
                parent_perm = compute_perm(cat.parent_id)
                permissions[cat.id] = parent_perm
                return parent_perm
                
            # If root and no parent:
            if cat.id == general_id:
                permissions[cat.id] = 'read'
                return 'read'
                
            permissions[cat.id] = None
            return None

        for cat in categories:
            compute_perm(cat)
            
        return permissions

    @api.model
    def _get_user_readable_category_ids(self):
        perms = self._get_user_permissions()
        return [cat_id for cat_id, perm in perms.items() if perm]

    @api.model
    def _get_user_readable_category_domain(self):
        readable_ids = self._get_user_readable_category_ids()
        if not readable_ids:
            return [('id', '=', 0)]
        return [('id', 'in', readable_ids)]

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
        perms = self._get_user_permissions()
        for category in self:
            perm = perms.get(category.id)
            category.user_can_upload_here = perm in ('write', 'delete')

    @api.model
    def _get_user_uploadable_category_ids(self, category_ids=None):
        perms = self._get_user_permissions()
        uploadable = {cat_id for cat_id, perm in perms.items() if perm in ('write', 'delete')}
        if category_ids is not None:
            return uploadable.intersection(category_ids)
        return uploadable

    def _check_user_can_upload_here(self):
        self.ensure_one()
        perms = self._get_user_permissions()
        return perms.get(self.id) in ('write', 'delete')

    def _check_access(self, operation):
        if self.env.su:
            return super()._check_access(operation)
            
        perms = self._get_user_permissions()
        for category in self:
            perm = perms.get(category.id)
            if not perm:
                raise AccessError(_("No tienes permiso para acceder a este directorio: %s") % category.complete_name)
                
            if operation == 'read':
                continue
            elif operation in ('write', 'create'):
                if perm not in ('write', 'delete'):
                    raise AccessError(_("No tienes permiso para modificar este directorio: %s") % category.complete_name)
            elif operation == 'unlink':
                if perm != 'delete':
                    raise AccessError(_("No tienes permiso para eliminar este directorio: %s") % category.complete_name)
                    
        return super()._check_access(operation)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            for vals in vals_list:
                parent_id = vals.get('parent_id')
                if parent_id:
                    parent = self.browse(parent_id)
                    perms = parent._get_user_permissions()
                    perm = perms.get(parent.id)
                    if perm not in ('write', 'delete'):
                        raise AccessError(_("No tienes permiso para crear subcarpetas en este directorio."))
                else:
                    if not (
                        self.env.user.has_group('rms_custom_knowledge.group_knowledge_manager')
                        or self.env.user.has_group('base.group_system')
                    ):
                        raise AccessError(_("Solo los gestores de Knowledge pueden crear directorios raíz."))
        return super().create(vals_list)

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
