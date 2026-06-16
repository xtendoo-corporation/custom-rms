from odoo import api, fields, models


class DocumentKnowledgeCategory(models.Model):
    _name = 'document.knowledge.category'
    _description = 'Document Knowledge Directory'
    _parent_name = 'parent_id'
    _parent_store = True
    _rec_name = 'complete_name'
    _order = 'complete_name, id'

    name = fields.Char(required=True, translate=True)
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
