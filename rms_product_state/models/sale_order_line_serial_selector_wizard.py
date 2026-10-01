from odoo import models, fields, api
from odoo.exceptions import UserError

STATE_CODE_SELECTION = [
    ('second_hand', '2ª Mano'),
    ('ex_demo', 'Ex-Demo'),
]


class SaleOrderLineSerialSelectorWizard(models.TransientModel):
    _name = 'sale.order.line.serial.selector.wizard'
    _description = 'Selector de números de serie 2ª Mano / Ex-Demo para una línea de venta'

    sale_order_line_id = fields.Many2one('sale.order.line', required=True)
    product_id = fields.Many2one(related='sale_order_line_id.product_id', readonly=True)
    state_code = fields.Selection(STATE_CODE_SELECTION, string='Estado', required=True)
    lot_ids = fields.Many2many(
        'stock.lot', 'sale_order_line_serial_wizard_lot_rel', 'wizard_id', 'lot_id',
        string='Números de serie disponibles',
    )
    lot_candidates = fields.Json(compute='_compute_lot_candidates')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        line_id = res.get('sale_order_line_id')
        if line_id:
            line = self.env['sale.order.line'].browse(line_id)
            if line.serial_ids:
                res['state_code'] = line.serial_ids[0].product_state_id.code
                res['lot_ids'] = [(6, 0, line.serial_ids.lot_id.ids)]
        return res

    @api.depends('product_id', 'state_code', 'sale_order_line_id')
    def _compute_lot_candidates(self):
        Lot = self.env['stock.lot']
        Serial = self.env['sale.order.line.serial']
        for wiz in self:
            if not (wiz.product_id and wiz.state_code):
                wiz.lot_candidates = []
                continue
            lots = Lot.search([
                ('product_id', '=', wiz.product_id.id),
                ('product_state_code', '=', wiz.state_code),
            ])
            reservations = Serial.search([
                ('lot_id', 'in', lots.ids),
                ('sale_order_line_id.order_id.state', '!=', 'cancel'),
                ('sale_order_line_id', '!=', wiz.sale_order_line_id.id),
            ])
            reserved_by = {
                res.lot_id.id: (res.sale_order_line_id.order_id.user_id.name or 'un comercial')
                for res in reservations
            }
            wiz.lot_candidates = [{
                'id': lot.id,
                'name': lot.name,
                'location': lot.location_id.display_name or '',
                'reserved_by': reserved_by.get(lot.id),
            } for lot in lots]

    def action_confirm(self):
        self.ensure_one()
        if not self.lot_ids:
            raise UserError('Selecciona al menos un número de serie.')
        line = self.sale_order_line_id
        # Se fija la cantidad ANTES de crear las series para que la validación
        # de consistencia (cantidad == nº de series) nunca vea un estado intermedio.
        line.serial_ids.unlink()
        line.product_uom_qty = len(self.lot_ids)
        self.env['sale.order.line.serial'].create([{
            'sale_order_line_id': line.id,
            'lot_id': lot.id,
            'price_unit': lot.custom_price,
        } for lot in self.lot_ids])
        return {'type': 'ir.actions.act_window_close'}

    def action_clear(self):
        self.ensure_one()
        self.sale_order_line_id.serial_ids.unlink()
        return {'type': 'ir.actions.act_window_close'}
