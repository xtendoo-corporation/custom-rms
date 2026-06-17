from odoo import _, api, fields, models
from odoo.exceptions import AccessError


class DocumentKnowledgeAccess(models.Model):
    _name = 'document.knowledge.access'
    _description = 'Document Knowledge Directory Access'
    _rec_name = 'user_id'
    _order = 'category_id, user_id'

    category_id = fields.Many2one(
        'document.knowledge.category',
        string='Directorio',
        required=True,
        ondelete='cascade',
        index=True,
    )
    user_id = fields.Many2one(
        'res.users',
        string='Usuario',
        required=True,
        ondelete='cascade',
        index=True,
    )
    permission = fields.Selection(
        [
            ('read', 'Ver'),
            ('read_upload', 'Ver y subir archivos'),
        ],
        string='Permiso',
        required=True,
        default='read',
    )

    _category_user_unique = models.Constraint(
        'UNIQUE(category_id, user_id)',
        'Este usuario ya tiene permisos en este directorio.',
    )

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
