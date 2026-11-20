# -*- coding: utf-8 -*-
"""Marcas de la carga de arranque en nº de serie, ubicaciones y depósitos."""
import re

from odoo import api, fields, models
from odoo.exceptions import UserError


class StockLocation(models.Model):
    _inherit = 'stock.location'

    rms_phantom = fields.Boolean(
        string='Pendiente de localizar (almacén fantasma)',
        help='Lo que Sage tenía y no se encontró en el recuento. No se puede vender ni reservar '
             'y no cuenta en la valoración del almacén.')

    @api.model
    def _rms_phantom_location(self, company, create=True):
        """Ubicación fantasma de la empresa. Tipo «Pérdida de inventario»: es el
        único tipo de ubicación con empresa que Odoo no valora, y ningún albarán
        la puede reservar porque no cuelga de ningún almacén."""
        Location = self.sudo().with_context(active_test=False)
        location = Location.search([('rms_phantom', '=', True), ('company_id', '=', company.id)], limit=1)
        if not location and create:
            parent = self.env.ref('stock.stock_location_locations_virtual', raise_if_not_found=False)
            location = Location.create({
                'name': 'Pendiente de localizar', 'usage': 'inventory', 'company_id': company.id,
                'rms_phantom': True, 'location_id': parent.id if parent else False,
            })
        return location


class StockLot(models.Model):
    _inherit = 'stock.lot'

    rms_unverified = fields.Boolean(
        string='No verificado', copy=False, index=True,
        help='Entró en la carga de arranque según Sage, sin que nadie lo haya visto. '
             'Se desmarca cuando se cuente.')
    rms_alta_review = fields.Boolean(
        string='Alta por revisar', copy=False, index=True,
        help='Se leyó en la nave y no estaba en Sage: entró a nombre de RMS. '
             'Administración debe revisar la empresa y el coste.')
    rms_initial_load_id = fields.Many2one('rms.initial.load', string='Carga de arranque', copy=False,
                                          index='btree_not_null', ondelete='set null')
    rms_stock_company_id = fields.Many2one('res.company', string='Empresa (donde está)',
                                           related='location_id.company_id')

    def action_rms_mark_verified(self):
        self.write({'rms_unverified': False})
        return True

    def action_rms_alta_reviewed(self):
        self.write({'rms_alta_review': False})
        return True

    def action_rms_alta_change_company(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': 'Cambiar la empresa del alta',
            'res_model': 'rms.initial.load.alta.company', 'view_mode': 'form', 'target': 'new',
            'context': {'default_lot_id': self.id},
        }

    @api.model
    def _rms_site_of(self, location):
        digits = re.search(r'(\d+)$', (location.warehouse_id.code or '').strip())
        return int(digits.group(1)) if digits else 0

    def _rms_change_company(self, company, location):
        """Pasa el equipo a otra empresa: baja de inventario en la empresa
        actual y alta en la nueva (Odoo no permite un traslado directo entre
        empresas)."""
        self.ensure_one()
        Load = self.env['rms.initial.load'].sudo()
        quants = self.env['stock.quant'].sudo().search([
            ('lot_id', '=', self.id), ('quantity', '>', 0), ('location_id.usage', '=', 'internal')])
        if len(quants) != 1:
            raise UserError('El equipo %s no está en una única ubicación interna: no se puede cambiar de empresa.'
                            % self.name)
        if quants.reserved_quantity:
            raise UserError('El equipo %s está reservado en un albarán.' % self.name)
        old_company = quants.location_id.company_id
        if old_company == company:
            raise UserError('El equipo ya está a nombre de %s.' % company.name)
        name = 'Cambio de empresa del alta %s' % self.name
        quantity = quants.quantity
        source = quants.location_id
        spec = [
            (old_company, source, Load._rms_loss_location(old_company, self.product_id)),
            (company, Load._rms_loss_location(company, self.product_id), location),
        ]
        for move_company, src, dest in spec:
            move = self.env['stock.move'].sudo().with_company(move_company).with_context(inventory_mode=False).create(
                Load._rms_move_vals(move_company, self.product_id, quantity, src, dest,
                                    lot=self, state=self.product_state_id, name=name))
            move._action_done()
        return True


class StockCession(models.Model):
    _inherit = 'stock.cession'

    rms_inherited_from_sage = fields.Boolean(
        string='Heredado de Sage, sin firma', copy=False, index=True,
        help='Depósito que ya existía en Sage al arrancar Odoo. Entró sin verificar y sin '
             'documento firmado por el cliente.')
    rms_sage_partner_name = fields.Char(string='Cliente según Sage', copy=False)
    rms_initial_load_id = fields.Many2one('rms.initial.load', string='Carga de arranque', copy=False,
                                          index='btree_not_null', ondelete='set null')
