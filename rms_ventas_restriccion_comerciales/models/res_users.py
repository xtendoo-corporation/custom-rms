# -*- coding: utf-8 -*-

from odoo import api, fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    # Para traspasos de cartera entre comerciales (p. ej. Vicente -> Alex): el
    # usuario trabaja también con los clientes, presupuestos y oportunidades de
    # los comerciales indicados, como si fueran suyos.
    rms_shared_customer_user_ids = fields.Many2many(
        comodel_name='res.users',
        relation='res_users_rms_shared_customer_rel',
        column1='user_id',
        column2='shared_user_id',
        string='Lleva también los clientes de',
        domain=[('share', '=', False)],
        help='Este comercial puede ver y presupuestar a los clientes de estos '
             'comerciales, y ver sus presupuestos y oportunidades.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        users = super().create(vals_list)
        if any(vals.get('rms_shared_customer_user_ids') for vals in vals_list):
            self.env.registry.clear_cache()
        return users

    def write(self, vals):
        res = super().write(vals)
        if 'rms_shared_customer_user_ids' in vals:
            # Las reglas de acceso se cachean por usuario.
            self.env.registry.clear_cache()
        return res
