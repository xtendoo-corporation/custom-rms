from odoo import fields, models
from odoo.exceptions import UserError


class RepairFactoryReturnWizard(models.TransientModel):
    _name = 'rms.repair.factory.return.wizard'
    _description = 'Vuelta de fábrica'

    repair_id = fields.Many2one('repair.order', required=True)
    result = fields.Selection([('repaired', 'Reparado'), ('replaced', 'Sustituido por otro'),
                               ('credited', 'Abonado por la fábrica')], string='Resultado', required=True, default='repaired')
    new_serial = fields.Char(string='Nº de serie nuevo')
    credit_ref = fields.Char(string='Nº de abono')

    def action_confirm(self):
        self.ensure_one()
        repair = self.repair_id
        if repair.rms_stage != 'factory':
            raise UserError('El equipo no está en fábrica.')
        if self.result == 'credited' and repair.rms_owner_type != 'company':
            raise UserError('Solo se pueden abonar equipos nuestros.')
        if self.result == 'replaced' and not (self.new_serial or '').strip():
            raise UserError('Indica el nº de serie nuevo.')
        warehouse = repair._rms_sat_locations()
        factory = warehouse.rms_sat_factory_location_id
        vendor = self.env.ref('stock.stock_location_suppliers')
        vals = {'rms_factory_result': self.result, 'rms_factory_back_date': fields.Date.context_today(repair),
                'rms_factory_credit_ref': self.credit_ref,
                'rms_stage': 'ready' if repair.state == 'done' else 'repair'}
        if self.result == 'repaired':
            repair._rms_customer_move(factory, warehouse.rms_sat_location_id, 'Vuelta de fábrica')
        else:
            old_lot = repair.lot_id
            if self.result == 'replaced':
                name = self.new_serial.strip()
                if name == old_lot.name:
                    raise UserError('El nº de serie nuevo debe ser distinto del anterior.')
                lot = self.env['stock.lot'].sudo().search([('name', '=', name), ('product_id', '=', repair.product_id.id),
                    ('company_id', 'in', [False, repair.company_id.id])], limit=1)
                if lot and lot.rms_replaces_lot_id and lot.rms_replaces_lot_id != old_lot:
                    raise UserError('El nº de serie ya sustituye a otro equipo.')
                lot = lot or self.env['stock.lot'].sudo().create({'name': name, 'product_id': repair.product_id.id,
                                                                  'company_id': repair.company_id.id})
                lot.rms_replaces_lot_id = old_lot
            repair._rms_customer_move(factory, vendor, 'Salida a fábrica')
            if self.result == 'replaced':
                repair.write({'rms_original_lot_id': repair.rms_original_lot_id.id or old_lot.id, 'lot_id': lot.id})
                repair._rms_customer_move(vendor, warehouse.rms_sat_location_id, 'Sustitución de fábrica')
            else:
                vals.update({'rms_stage': 'delivered', 'rms_in_sat': False})
        if self.result != 'credited':
            vals.update({'product_location_src_id': warehouse.rms_sat_location_id.id,
                         'product_location_dest_id': warehouse.rms_sat_location_id.id})
        repair.write(vals)
        return {'type': 'ir.actions.act_window_close'}
