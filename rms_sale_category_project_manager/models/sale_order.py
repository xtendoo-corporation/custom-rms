# -*- coding: utf-8 -*-

from odoo import api, fields, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    category_project_manager_ids = fields.Many2many(
        comodel_name='res.users',
        relation='sale_order_category_project_manager_rel',
        column1='order_id',
        column2='user_id',
        string='Project Managers',
        compute='_compute_category_project_manager_ids',
        store=True,
        readonly=True,
        copy=False,
        help='Project managers assigned automatically from the product categories used in the quotation lines.',
    )

    @api.depends('order_line.product_id', 'order_line.product_id.categ_id', 'order_line.product_id.categ_id.project_manager_ids')
    def _compute_category_project_manager_ids(self):
        for order in self:
            users = order.order_line.product_id.categ_id.project_manager_ids
            order.category_project_manager_ids = [(6, 0, users.ids)]

    @api.onchange('order_line', 'order_line.product_id')
    def _onchange_category_project_manager_ids(self):
        for order in self:
            users = order.order_line.product_id.categ_id.project_manager_ids
            order.category_project_manager_ids = [(6, 0, users.ids)]

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        orders._subscribe_category_project_managers()
        return orders

    def write(self, vals):
        result = super().write(vals)
        if 'order_line' in vals:
            self._subscribe_category_project_managers()
        return result

    def _subscribe_category_project_managers(self):
        for order in self:
            partner_ids = order.category_project_manager_ids.filtered(
                lambda user: user.active and user.partner_id
            ).mapped('partner_id').ids
            if partner_ids:
                order.message_subscribe(partner_ids=partner_ids)
