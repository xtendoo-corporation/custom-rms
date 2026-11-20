# -*- coding: utf-8 -*-
"""Altas por revisar: cambiar la empresa de un equipo que entró a nombre de RMS."""
from odoo import api, fields, models
from odoo.exceptions import UserError


class InitialLoadAltaCompany(models.TransientModel):
    _name = 'rms.initial.load.alta.company'
    _description = 'Cambiar la empresa de un alta de la carga de arranque'

    lot_id = fields.Many2one('stock.lot', string='Nº de serie', required=True, readonly=True)
    product_id = fields.Many2one(related='lot_id.product_id', string='Producto')
    current_location_id = fields.Many2one(related='lot_id.location_id', string='Está en')
    current_company_id = fields.Many2one(related='lot_id.location_id.company_id', string='Empresa actual')
    company_id = fields.Many2one('res.company', string='Empresa correcta', required=True)
    location_id = fields.Many2one('stock.location', string='Entra en', compute='_compute_location_id')
    clear_mark = fields.Boolean(string='Dar el alta por revisada', default=True)

    @api.depends('company_id', 'lot_id')
    def _compute_location_id(self):
        Warehouse = self.env['stock.warehouse'].sudo()
        for wizard in self:
            location = self.env['stock.location']
            if wizard.company_id and wizard.lot_id.location_id:
                site = self.env['stock.lot']._rms_site_of(wizard.lot_id.location_id)
                warehouses = Warehouse.search([('company_id', '=', wizard.company_id.id)])
                same_site = warehouses.filtered(
                    lambda w: site and self.env['stock.lot']._rms_site_of(w.lot_stock_id) == site)
                location = (same_site or warehouses)[:1].lot_stock_id
            wizard.location_id = location

    def action_apply(self):
        self.ensure_one()
        if not self.env.user.has_group('stock.group_stock_manager'):
            raise UserError('Solo un responsable de inventario puede cambiar la empresa de un alta.')
        if not self.location_id:
            raise UserError('La empresa %s no tiene almacén donde dejar el equipo.' % self.company_id.name)
        self.lot_id._rms_change_company(self.company_id, self.location_id.sudo())
        if self.clear_mark:
            self.lot_id.sudo().rms_alta_review = False
        return {'type': 'ir.actions.act_window_close'}
