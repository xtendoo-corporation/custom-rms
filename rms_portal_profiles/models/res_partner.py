from odoo import fields, models

PORTAL_PROFILE_GROUP_XMLIDS = {
    'customer': 'rms_portal_profiles.group_portal_customer',
    'marketing': 'rms_portal_profiles.group_portal_marketing',
    'projects': 'rms_portal_profiles.group_portal_projects',
}


class ResPartner(models.Model):
    _inherit = 'res.partner'

    portal_profile = fields.Selection(
        [
            ('customer', 'Cliente'),
            ('marketing', 'Colaborador de Marketing'),
            ('projects', 'Proyectos'),
        ],
        string='Perfil de portal', default='customer', tracking=True,
        help='Determina qué secciones del portal de clientes puede ver este contacto.',
    )

    def write(self, vals):
        res = super().write(vals)
        if 'portal_profile' in vals:
            self._sync_portal_profile_groups()
        return res

    def _sync_portal_profile_groups(self):
        all_profile_groups = self.env['res.groups']
        for xmlid in PORTAL_PROFILE_GROUP_XMLIDS.values():
            all_profile_groups |= self.env.ref(xmlid)

        for partner in self:
            portal_users = partner.user_ids.filtered('share')
            if not portal_users:
                continue
            target_xmlid = PORTAL_PROFILE_GROUP_XMLIDS.get(partner.portal_profile)
            if not target_xmlid:
                continue
            target_group = self.env.ref(target_xmlid)
            portal_users.write({
                'group_ids': [(3, group.id) for group in all_profile_groups] + [(4, target_group.id)],
            })
