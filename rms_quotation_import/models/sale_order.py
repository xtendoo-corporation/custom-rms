# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError
import datetime

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def action_group_in_opportunities(self):
        # Ensure we have active records selected
        if not self:
            raise UserError(_("Por favor, selecciona al menos un presupuesto."))

        # Dict to group orders by (partner_id, month_year_str)
        groups = {}
        for order in self:
            if not order.partner_id:
                continue
            
            # Format order date to Month/Year
            order_date = order.date_order or fields.Datetime.now()
            if isinstance(order_date, str):
                try:
                    dt = fields.Datetime.from_string(order_date)
                except Exception:
                    dt = datetime.datetime.now()
            else:
                dt = order_date
            
            month_year = dt.strftime('%m/%Y')
            key = (order.partner_id.id, month_year)
            
            if key not in groups:
                groups[key] = {
                    'partner': order.partner_id,
                    'month_year': month_year,
                    'orders': self.env['sale.order']
                }
            groups[key]['orders'] |= order

        crm_lead_model = self.env['crm.lead']
        created_opp_count = 0
        opportunity_ids = set()

        for key, g_data in groups.items():
            partner = g_data['partner']
            month_year = g_data['month_year']
            orders = g_data['orders']
            
            opp_name = _("%s - Oportunidad %s") % (partner.name, month_year)
            
            # Get salesperson (user_id) from the orders
            user_id = False
            for order in orders:
                if order.user_id:
                    user_id = order.user_id.id
                    break
            
            # Search for an existing opportunity for this partner and with this name
            opp = crm_lead_model.search([
                ('partner_id', '=', partner.id),
                ('name', '=', opp_name),
                ('type', '=', 'opportunity')
            ], limit=1)
            
            if not opp:
                opp_vals = {
                    'name': opp_name,
                    'partner_id': partner.id,
                    'type': 'opportunity',
                }
                if user_id:
                    opp_vals['user_id'] = user_id
                opp = crm_lead_model.create(opp_vals)
                created_opp_count += 1
            elif user_id and opp.user_id.id != user_id:
                opp.write({'user_id': user_id})
            
            opportunity_ids.add(opp.id)
            
            # Link all grouped sale orders to the opportunity
            orders.write({'opportunity_id': opp.id})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Agrupación en Oportunidades'),
                'message': _('Se han agrupado %d presupuestos en %d oportunidades (%d creadas nuevas).') % (
                    len(self), len(opportunity_ids), created_opp_count
                ),
                'sticky': False,
                'type': 'success',
            }
        }
