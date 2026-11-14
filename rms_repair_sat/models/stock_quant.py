# -*- coding: utf-8 -*-
from odoo import api, models


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    @api.model
    def _get_available_quantity(self, product_id, location_id, lot_id=None, package_id=None, owner_id=None,
                                strict=False, allow_negative=False):
        """repair.action_repair_done busca el equipo del cliente en la ubicación
        de PIEZAS (repair.location_id) para ponerle propietario; el del SAT está
        en la ubicación SAT y el movimiento salía sin propietario (cantidades
        negativas y valoración). Para las reparaciones SAT se responde con lo
        que el cliente tiene en la ubicación SAT, así Odoo pone propietario =
        cliente."""
        pairs = self.env.context.get('rms_sat_owner_pairs')
        if pairs and owner_id:
            key = (product_id.id, lot_id.id if lot_id else False, owner_id.id)
            sat_location = {tuple(p[:3]): p[3] for p in pairs}.get(key)
            if sat_location and sat_location != location_id.id:
                location_id = self.env['stock.location'].browse(sat_location)
        return super()._get_available_quantity(product_id, location_id, lot_id=lot_id, package_id=package_id,
                                               owner_id=owner_id, strict=strict, allow_negative=allow_negative)
