# -*- coding: utf-8 -*-

from odoo import api, fields, models
from odoo.exceptions import UserError

from .restrictions import own_customers_domain


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # Todas las oportunidades del contacto (opportunity_ids de crm solo incluye
    # las de tipo oportunidad). Se usa en la regla de acceso de los contactos
    # de las oportunidades asignadas a un comercial.
    rms_crm_lead_ids = fields.One2many(
        comodel_name='crm.lead',
        inverse_name='partner_id',
        string='Oportunidades y leads',
    )

    rms_is_own_customer = fields.Boolean(
        string='Es cliente mío',
        compute='_compute_rms_is_own_customer',
        search='_search_rms_is_own_customer',
        help='El Vendedor del cliente (o de su empresa) es el usuario o uno de '
             'los comerciales cuyos clientes lleva también.',
    )

    @api.depends_context('uid')
    def _compute_rms_is_own_customer(self):
        own = self.filtered_domain(own_customers_domain(self.env))
        for partner in self:
            partner.rms_is_own_customer = partner in own

    def _search_rms_is_own_customer(self, operator, value):
        if operator in ('=', '!='):
            values, negate = {bool(value)}, operator == '!='
        elif operator in ('in', 'not in'):
            values, negate = {bool(v) for v in value}, operator == 'not in'
        else:
            raise UserError('Operador de búsqueda no admitido: %s' % operator)
        if len(values) != 1:
            # True y False a la vez: todos o ninguno.
            return [('id', '=', 0)] if negate else []
        domain = own_customers_domain(self.env)
        return domain if (True in values) != negate else ['!'] + domain
