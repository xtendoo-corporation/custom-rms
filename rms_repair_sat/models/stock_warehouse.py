# -*- coding: utf-8 -*-
import re

from odoo import api, fields, models

# Sedes del SAT: el número del almacén de Odoo (RMS1/ET1/RJB1 = Madrid, RMS7/ET7/RJB7 = Sevilla).
SAT_SITES = {'1': ('madrid', 'SAT Madrid'), '7': ('sevilla', 'SAT Sevilla')}


class StockWarehouse(models.Model):
    _inherit = 'stock.warehouse'

    rms_ra_location_id = fields.Many2one('stock.location', string='Ubicación RA', copy=False)
    rms_sat_location_id = fields.Many2one('stock.location', string='Ubicación SAT', copy=False)
    rms_sat_factory_location_id = fields.Many2one('stock.location', string='Ubicación "En fábrica"', copy=False)
    rms_sat_picking_type_id = fields.Many2one('stock.picking.type', string='Tipo de operación SAT', copy=False)

    def _rms_sat_site(self):
        self.ensure_one()
        match = re.search(r'(\d+)$', (self.code or '').strip())
        return SAT_SITES.get(match.group(1)) if match else None

    @api.model
    def _rms_setup_sat(self):
        """Crea (si faltan) las ubicaciones "SAT Madrid"/"SAT Sevilla" con su
        hija "En fábrica", su tipo de operación de reparación y la ubicación
        "Despiece" de cada empresa. Idempotente; NO se ejecuta al instalar:
        lo lanza un responsable (menú SAT > Configuración)."""
        Location = self.env['stock.location'].sudo()
        summary = {'creadas': [], 'existentes': [], 'despiece': []}
        for warehouse in self.sudo().search([]):
            site = warehouse._rms_sat_site()
            if not site:
                continue
            label = site[1]
            if not warehouse.rms_sat_location_id:
                warehouse.rms_sat_location_id = Location.create({
                    'name': label, 'usage': 'internal', 'location_id': warehouse.view_location_id.id,
                    'company_id': warehouse.company_id.id})
                summary['creadas'].append('%s/%s' % (warehouse.code, label))
            else:
                summary['existentes'].append('%s/%s' % (warehouse.code, label))
            ra_label = 'RA Madrid' if site[0] == 'madrid' else 'RA Sevilla'
            if not warehouse.rms_ra_location_id:
                warehouse.rms_ra_location_id = Location.search([
                    ('name', '=', ra_label), ('location_id', '=', warehouse.view_location_id.id),
                    ('company_id', '=', warehouse.company_id.id), ('usage', '=', 'internal')], limit=1) or Location.create({
                        'name': ra_label, 'usage': 'internal', 'location_id': warehouse.view_location_id.id,
                        'company_id': warehouse.company_id.id})
                summary['creadas'].append('%s/%s' % (warehouse.code, ra_label))
            else:
                summary['existentes'].append('%s/%s' % (warehouse.code, ra_label))
            if not warehouse.rms_sat_factory_location_id:
                warehouse.rms_sat_factory_location_id = Location.create({
                    'name': 'En fábrica', 'usage': 'internal', 'location_id': warehouse.rms_sat_location_id.id,
                    'company_id': warehouse.company_id.id})
            if not warehouse.rms_sat_picking_type_id and warehouse.repair_type_id:
                warehouse.rms_sat_picking_type_id = warehouse.repair_type_id.sudo().copy({
                    'name': 'Reparaciones %s' % label,
                    'sequence_code': 'SAT',
                    # Piezas: del stock del almacén. Equipo del cliente: en la ubicación SAT.
                    'default_location_src_id': warehouse.lot_stock_id.id,
                    'default_product_location_src_id': warehouse.rms_sat_location_id.id,
                    'default_product_location_dest_id': warehouse.rms_sat_location_id.id,
                })
        for company in self.env['res.company'].sudo().search([]):
            if not self.env['stock.location']._rms_disassembly_location(company, create=False):
                self.env['stock.location']._rms_disassembly_location(company)
                summary['despiece'].append(company.name)
        return summary


class StockLocation(models.Model):
    _inherit = 'stock.location'

    rms_disassembly = fields.Boolean(string='Ubicación de despiece', copy=False)

    @api.model
    def _rms_disassembly_location(self, company, create=True):
        location = self.sudo().search([('rms_disassembly', '=', True), ('company_id', '=', company.id)], limit=1)
        if not location and create:
            parent = self.env.ref('stock.stock_location_locations_virtual', raise_if_not_found=False)
            location = self.sudo().create({
                'name': 'Despiece', 'usage': 'inventory', 'rms_disassembly': True,
                'company_id': company.id, 'location_id': parent.id if parent else False})
        return location
