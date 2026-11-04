# -*- coding: utf-8 -*-

from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # Odoo solo admite un Vendedor (user_id) por cliente. Cuando un cliente lo
    # llevan varios comerciales, los demás se añaden aquí para que también
    # puedan hacerle presupuestos (ver own_customers_domain).
    rms_shared_user_ids = fields.Many2many(
        comodel_name='res.users',
        relation='res_partner_rms_shared_user_rel',
        column1='partner_id',
        column2='user_id',
        string='Otros comerciales',
        domain=[('share', '=', False)],
        help='Comerciales que, además del Vendedor, también llevan este cliente '
             'y pueden hacerle presupuestos. Se aplica también a sus contactos.',
    )
