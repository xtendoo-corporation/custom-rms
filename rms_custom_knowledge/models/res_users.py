from odoo import api, fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    rms_knowledge_manager = fields.Boolean(
        string='Gestor de Conocimiento',
        compute='_compute_rms_knowledge_manager',
        inverse='_inverse_rms_knowledge_manager',
        compute_sudo=True,
    )

    @api.depends('groups_id')
    def _compute_rms_knowledge_manager(self):
        group = self.env.ref('rms_custom_knowledge.group_knowledge_manager', raise_if_not_found=False)
        for user in self:
            user.rms_knowledge_manager = bool(group and group in user.groups_id)

    def _inverse_rms_knowledge_manager(self):
        group = self.env.ref('rms_custom_knowledge.group_knowledge_manager', raise_if_not_found=False)
        if not group:
            return
        for user in self:
            command = (4, group.id) if user.rms_knowledge_manager else (3, group.id)
            user.groups_id = [command]
