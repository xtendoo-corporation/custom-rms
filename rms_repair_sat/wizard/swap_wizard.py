from odoo import api, fields, models, Command
from odoo.exceptions import UserError


class RepairSwapWizard(models.TransientModel):
    _name = 'rms.repair.swap.wizard'
    _description = 'Cambio en garantía'

    repair_id = fields.Many2one('repair.order', required=True)
    product_id = fields.Many2one('product.product', string='Equipo de sustitución', required=True)
    lot_id = fields.Many2one('stock.lot', string='Nº de serie nuevo', required=True)
    available_lot_ids = fields.Many2many('stock.lot', compute='_compute_available_lots')
    note = fields.Text(string='Nota')

    @api.model
    def default_get(self, names):
        values = super().default_get(names)
        repair = self.env['repair.order'].browse(values.get('repair_id') or self.env.context.get('default_repair_id'))
        if repair and 'product_id' in names:
            values['product_id'] = repair.product_id.id
        return values

    @api.depends('product_id', 'repair_id', 'repair_id.rms_site')
    def _compute_available_lots(self):
        for wizard in self:
            warehouse = wizard.repair_id._rms_warehouse() if wizard.repair_id else self.env['stock.warehouse']
            quants = self.env['stock.quant'].search([('product_id', '=', wizard.product_id.id),
                ('location_id', 'child_of', warehouse.lot_stock_id.id), ('owner_id', '=', False),
                ('lot_id', '!=', False), ('quantity', '>', 0)]) if warehouse and wizard.product_id else self.env['stock.quant']
            wizard.available_lot_ids = quants.filtered(lambda q: q.quantity - q.reserved_quantity >= 1).lot_id

    def action_confirm(self):
        self.ensure_one()
        repair = self.repair_id
        if not repair.under_warranty or not repair.rms_in_sat or repair.rms_owner_type != 'customer' or repair.rms_swap_done or repair.rms_stage == 'factory':
            raise UserError('El equipo debe estar en el SAT, ser del cliente y estar en garantía.')
        warehouse = repair._rms_sat_locations()
        if not warehouse.rms_ra_location_id:
            raise UserError('Falta la ubicación RA de la sede.')
        self._compute_available_lots()
        if self.lot_id not in self.available_lot_ids or self.lot_id.product_id != self.product_id:
            raise UserError('El nº de serie nuevo no está disponible en el stock del almacén.')
        quant = self.env['stock.quant'].search([('product_id', '=', self.product_id.id),
            ('lot_id', '=', self.lot_id.id), ('location_id', 'child_of', warehouse.lot_stock_id.id),
            ('owner_id', '=', False), ('quantity', '>', 0)]).filtered(
                lambda q: q.quantity - q.reserved_quantity >= 1)[:1]
        customers = self.env.ref('stock.stock_location_customers')
        picking = self.env['stock.picking'].create({
            'picking_type_id': warehouse.out_type_id.id, 'location_id': warehouse.lot_stock_id.id,
            'location_dest_id': customers.id, 'partner_id': repair.partner_id.id,
            'origin': repair.name, 'company_id': repair.company_id.id,
            'move_ids': [Command.create({'product_id': self.product_id.id,
                'product_uom': self.product_id.uom_id.id, 'product_uom_qty': 1,
                'location_id': warehouse.lot_stock_id.id, 'location_dest_id': customers.id})]})
        picking.action_confirm()
        move = picking.move_ids
        move.move_line_ids.unlink()
        self.env['stock.move.line'].create({'move_id': move.id, 'picking_id': picking.id,
            'product_id': self.product_id.id, 'product_uom_id': self.product_id.uom_id.id,
            'quantity': 1, 'lot_id': self.lot_id.id, 'location_id': quant.location_id.id,
            'location_dest_id': customers.id, 'company_id': repair.company_id.id})
        move.picked = True
        picking._action_done()
        repair._rms_customer_move(warehouse.rms_sat_location_id, customers, 'Cambio en garantía')
        partner = repair.partner_id
        repair.rms_owner_type = 'company'
        repair._rms_customer_move(customers, warehouse.rms_ra_location_id, 'Equipo averiado en RA')
        repair.write({'rms_swap_done': True, 'rms_swap_date': fields.Date.context_today(repair),
                      'rms_original_partner_id': partner.id, 'rms_swap_lot_id': self.lot_id.id,
                      'rms_swap_picking_id': picking.id, 'rms_swap_note': self.note,
                      'product_location_src_id': warehouse.rms_ra_location_id.id,
                      'product_location_dest_id': warehouse.rms_ra_location_id.id})
        return {'type': 'ir.actions.act_window_close'}
