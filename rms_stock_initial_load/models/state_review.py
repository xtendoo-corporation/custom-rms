# -*- coding: utf-8 -*-
"""Revisión de estados: equipos cuya lectura dice un estado distinto al de
Sage. Se deciden uno a uno antes de aplicar la carga."""
from odoo import api, fields, models
from odoo.exceptions import UserError

from .initial_load import SAGE_STATE_CODE, SAGE_STATES, SITE_NAMES


class InitialLoadStateReview(models.Model):
    _name = 'rms.initial.load.state.review'
    _description = 'Revisión de estado de un equipo de la carga de arranque'
    _order = 'state desc, site_number, product_id, serial, id'
    _rec_name = 'serial'

    load_id = fields.Many2one('rms.initial.load', string='Carga', required=True, ondelete='cascade', index=True)
    load_state = fields.Selection(related='load_id.state', string='Situación de la carga')
    company_id = fields.Many2one('res.company', string='Empresa', readonly=True)
    site_number = fields.Integer(string='Nº de nave', readonly=True, aggregator=False)
    site_name = fields.Char(string='Nave', compute='_compute_site_name', store=True)
    product_id = fields.Many2one('product.product', string='Producto', required=True, readonly=True)
    serial = fields.Char(string='Nº de serie', readonly=True)
    serial_normalized = fields.Char(readonly=True, index=True)
    sage_state = fields.Selection(SAGE_STATES, string='Estado en Sage', readonly=True)
    scanned_state_id = fields.Many2one('product.state', string='Estado marcado al leer', readonly=True)
    session_id = fields.Many2one('rms.stock.count.session', string='Recuento', readonly=True, ondelete='set null')
    scan_id = fields.Many2one('rms.stock.count.scan', string='Lectura', readonly=True, ondelete='set null')
    sage_line_id = fields.Many2one('rms.sage.stock.line', string='Línea de Sage', readonly=True, ondelete='set null')
    final_state_id = fields.Many2one('product.state', string='Estado final', readonly=True)
    state = fields.Selection([('pending', 'Por revisar'), ('done', 'Revisado')], string='Revisión',
                             default='pending', required=True, readonly=True, index=True)
    reviewed_by = fields.Many2one('res.users', string='Revisado por', readonly=True)
    reviewed_on = fields.Datetime(string='Revisado el', readonly=True)

    @api.depends('site_number')
    def _compute_site_name(self):
        for review in self:
            review.site_name = SITE_NAMES.get(review.site_number) or 'Sin nave'

    def _set_final(self, code):
        if not self.env.user.has_group('stock.group_stock_manager'):
            raise UserError('Solo un responsable de inventario puede revisar los estados.')
        if any(review.load_id.state == 'applied' for review in self):
            raise UserError('La carga ya está aplicada: el estado se cambia ahora en el nº de serie.')
        states = {state.code: state for state in self.env['product.state'].search([])}
        Line = self.env['rms.initial.load.line'].sudo()
        for review in self.sudo():
            state_code = code or SAGE_STATE_CODE.get(review.sage_state, 'new')
            state = states.get(state_code)
            if not state:
                raise UserError('No existe el estado «%s» en Odoo.' % state_code)
            review.write({'final_state_id': state.id, 'state': 'done', 'reviewed_by': self.env.user.id,
                          'reviewed_on': fields.Datetime.now()})
            Line.search([('review_id', '=', review.id)]).write({'state_id': state.id})
        self.sudo().load_id._refresh_summary()
        return True

    def action_set_new(self):
        return self._set_final('new')

    def action_set_demo(self):
        return self._set_final('demo')

    def action_set_ex_demo(self):
        return self._set_final('ex_demo')

    def action_set_second_hand(self):
        return self._set_final('second_hand')

    def action_use_sage(self):
        """Botón rápido «Poner el de Sage» (Sage demo -> Demo, nunca Ex-Demo)."""
        return self._set_final(None)

    def action_keep_scanned(self):
        """Dar por bueno el estado que marcó el operario."""
        for review in self:
            review._set_final(review.scanned_state_id.code)
        return True

    def action_reset(self):
        if any(review.load_id.state == 'applied' for review in self):
            raise UserError('La carga ya está aplicada.')
        Line = self.env['rms.initial.load.line'].sudo()
        for review in self.sudo():
            review.write({'final_state_id': False, 'state': 'pending', 'reviewed_by': False, 'reviewed_on': False})
            Line.search([('review_id', '=', review.id)]).write({'state_id': review.scanned_state_id.id})
        self.sudo().load_id._refresh_summary()
        return True
