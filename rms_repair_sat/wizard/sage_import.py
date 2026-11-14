# -*- coding: utf-8 -*-
"""Arranque: crea reparaciones abiertas con los equipos que Sage tiene hoy en
los almacenes del SAT (AL8 / A.8 / STM / STS).

Usa rms.sage.stock.line de rms_stock_count_session si está instalado. No es
dependencia: si no está, el asistente lo dice y no hace nada."""
from odoo import api, fields, models
from odoo.exceptions import UserError

SAT_SAGE_CODES = ('AL8', 'A.8', 'STM', 'STS')
# Pendiente de confirmar con Administración: STS = Sevilla, el resto Madrid.
SAGE_SITE = {'STS': 'sevilla'}
PENDING_PARTNER = 'Cliente pendiente de asignar (SAT)'


class RmsRepairSatSageImport(models.TransientModel):
    _name = 'rms.repair.sat.sage.import'
    _description = 'Crear reparaciones abiertas desde Sage'

    warehouse_codes = fields.Char(string='Almacenes Sage', default=', '.join(SAT_SAGE_CODES), readonly=True)
    preview_count = fields.Integer(string='Equipos en Sage', compute='_compute_preview')
    already_count = fields.Integer(string='Ya tienen reparación', compute='_compute_preview')
    unmatched_count = fields.Integer(string='Sin producto en Odoo (no se crean)', compute='_compute_preview')
    available = fields.Boolean(compute='_compute_preview')

    @api.model
    def _lines(self):
        if 'rms.sage.stock.line' not in self.env:
            return None
        return self.env['rms.sage.stock.line'].sudo().search([
            ('is_current', '=', True), ('stock_kind', '=', 'stock'), ('quantity', '>', 0),
            ('warehouse_code', 'in', list(SAT_SAGE_CODES)), ('company_id', '=', self.env.company.id)])

    @api.model
    def _existing_keys(self):
        repairs = self.env['repair.order'].sudo().search([
            ('company_id', '=', self.env.company.id), ('state', '!=', 'cancel'), ('rms_stage', '!=', 'delivered')])
        return {(r.product_id.id, (r.lot_id.name or r.rms_serial_in or '').strip().upper()) for r in repairs}

    def _compute_preview(self):
        lines = self._lines()
        keys = self._existing_keys() if lines is not None else set()
        for wizard in self:
            wizard.available = lines is not None
            if lines is None:
                wizard.preview_count = wizard.already_count = wizard.unmatched_count = 0
                continue
            matched = lines.filtered('product_id')
            wizard.preview_count = len(lines)
            wizard.unmatched_count = len(lines - matched)
            wizard.already_count = len(matched.filtered(
                lambda l: (l.product_id.id, (l.serial or '').strip().upper()) in keys))

    @api.model
    def _pending_partner(self):
        Partner = self.env['res.partner'].sudo()
        return Partner.search([('name', '=', PENDING_PARTNER)], limit=1) or Partner.create({
            'name': PENDING_PARTNER,
            'comment': 'Equipos que estaban en el SAT al arrancar Odoo: asignar el cliente real.'})

    def action_import(self):
        self.ensure_one()
        lines = self._lines()
        if lines is None:
            raise UserError('No está instalado el inventario de Sage (rms_stock_count_session).')
        partner = self._pending_partner()
        keys = self._existing_keys()
        Repair = self.env['repair.order']
        Lot = self.env['stock.lot'].sudo()
        created = Repair
        for line in lines.filtered('product_id'):
            serial = (line.serial or '').strip()
            key = (line.product_id.id, serial.upper())
            if key in keys:
                continue
            keys.add(key)
            vals = {
                'product_id': line.product_id.id, 'partner_id': partner.id, 'company_id': self.env.company.id,
                'rms_site': SAGE_SITE.get(line.warehouse_code, 'madrid'), 'rms_serial_in': serial or False,
                'rms_fault': 'Equipo en el SAT al arrancar (Sage %s, %s)' % (line.warehouse_code, line.article_code),
                'internal_notes': 'Creado desde Sage. Revisar cliente, avería y fase.',
            }
            if serial and line.product_id.tracking != 'none':
                lot = Lot.search([('product_id', '=', line.product_id.id), ('name', '=', serial),
                                  ('company_id', 'in', [self.env.company.id, False])], limit=1)
                if lot:
                    vals['lot_id'] = lot.id
            created |= Repair.create(vals)
        return {
            'type': 'ir.actions.act_window', 'name': 'Reparaciones creadas desde Sage', 'res_model': 'repair.order',
            'view_mode': 'list,form', 'domain': [('id', 'in', created.ids)],
        }
