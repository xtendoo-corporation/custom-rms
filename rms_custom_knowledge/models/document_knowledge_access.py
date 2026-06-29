from odoo import _, api, fields, models
from odoo.exceptions import AccessError


class DocumentKnowledgeAccess(models.Model):
    _name = 'document.knowledge.access'
    _description = 'Document Knowledge Directory Access'
    _rec_name = 'group_id'
    _order = 'category_id, group_id'

    category_id = fields.Many2one(
        'document.knowledge.category',
        string='Directorio',
        required=True,
        ondelete='cascade',
        index=True,
    )
    group_id = fields.Many2one(
        'res.groups',
        string='Grupo de usuarios',
        required=True,
        ondelete='cascade',
        index=True,
    )
    permission = fields.Selection(
        [
            ('read', 'Lectura'),
            ('write', 'Lectura y Escritura'),
            ('delete', 'Lectura, Escritura y Eliminación'),
        ],
        string='Permiso',
        required=True,
        default='read',
    )

    _sql_constraints = [
        ('category_group_unique', 'UNIQUE(category_id, group_id)', 'Este grupo ya tiene permisos en este directorio.'),
    ]

    def _check_can_manage_knowledge_access(self):
        if not (
            self.env.user.has_group('rms_custom_knowledge.group_knowledge_manager')
            or self.env.user.has_group('base.group_system')
        ):
            raise AccessError(_('Solo un gestor de Knowledge puede modificar permisos de directorio.'))

    @api.model_create_multi
    def create(self, vals_list):
        self._check_can_manage_knowledge_access()
        return super().create(vals_list)

    def write(self, vals):
        self._check_can_manage_knowledge_access()
        return super().write(vals)

    def unlink(self):
        self._check_can_manage_knowledge_access()
        return super().unlink()

    def init(self):
        super().init()
        self.env.cr.execute("""
            DELETE FROM document_knowledge_access;
            ALTER TABLE document_knowledge_access DROP CONSTRAINT IF EXISTS document_knowledge_access_category_user_unique;
            ALTER TABLE document_knowledge_access DROP CONSTRAINT IF EXISTS document_knowledge_access_category_id_user_id_key;
        """)
