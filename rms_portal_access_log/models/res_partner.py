from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    portal_activity_count = fields.Integer(
        string='Actividad en el portal', compute='_compute_portal_activity_count',
        groups='base.group_user',
    )

    def _compute_portal_activity_count(self):
        counts = dict(self.env['rms.portal.activity']._read_group(
            [('commercial_partner_id', 'in', self.commercial_partner_id.ids)],
            ['commercial_partner_id'], ['__count'],
        ))
        for partner in self:
            partner.portal_activity_count = counts.get(partner.commercial_partner_id, 0)

    def action_open_portal_interest(self):
        """Abre las fichas que más mira la empresa; si aún no ha mirado
        ninguna (solo pedidos, facturas...), abre la actividad completa."""
        self.ensure_one()
        company = self.commercial_partner_id
        domain = [('commercial_partner_id', '=', company.id)]
        if self.env['rms.portal.interest'].search_count(domain, limit=1):
            xmlid, title = 'rms_portal_access_log.action_portal_interest', 'Intereses de %s'
        else:
            xmlid, title = 'rms_portal_access_log.action_portal_activity', 'Actividad de %s'
        action = self.env['ir.actions.act_window']._for_xml_id(xmlid)
        action['domain'] = domain
        action['context'] = {'search_default_group_partner': 1}
        action['name'] = title % company.display_name
        return action
