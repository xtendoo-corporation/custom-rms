# -*- coding: utf-8 -*-
"""Despiece de un equipo propio (p. ej. una mesa antigua) en piezas de 2ª mano.

No se usa mrp.unbuild directamente: en Odoo 19 un desmontaje sin orden de
fabricación no acepta piezas con lote/nº de serie (y el estado "2ª mano" de
rms_product_state vive en el lote) y valora las piezas a su coste estándar en
vez de repartir el coste del equipo. La lista de materiales (mrp.bom) sí se usa
como plantilla de piezas por modelo: se carga y se puede guardar desde aquí.
"""
from odoo import Command, api, fields, models
from odoo.exceptions import AccessError, UserError


class RmsDisassembly(models.Model):
    _name = 'rms.disassembly'
    _description = 'Despiece de equipo'
    _inherit = ['mail.thread']
    _order = 'id desc'

    name = fields.Char(string='Referencia', default='Nuevo', copy=False, readonly=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    location_id = fields.Many2one('stock.location', string='Ubicación', required=True,
                                  domain="[('usage', '=', 'internal'), ('company_id', 'in', [company_id, False])]",
                                  default=lambda self: self.env['stock.warehouse'].search(
                                      [('company_id', '=', self.env.company.id)], limit=1).lot_stock_id)
    product_id = fields.Many2one('product.product', string='Equipo que se despieza', required=True,
                                 domain="[('is_storable', '=', True)]")
    lot_id = fields.Many2one('stock.lot', string='Nº de serie del equipo',
                             domain="[('product_id', '=', product_id)]")
    bom_id = fields.Many2one('mrp.bom', string='Plantilla de piezas (LdM de despiece)',
                             domain="[('product_tmpl_id.product_variant_ids', 'in', product_id)]")
    allocation = fields.Selection([('price', 'Proporcional al precio de venta'), ('equal', 'A partes iguales')],
                                  string='Reparto del coste', default='price', required=True)
    cost_total = fields.Float(string='Coste del equipo', compute='_compute_cost_total', store=True,
                              readonly=False, digits='Product Price')
    line_ids = fields.One2many('rms.disassembly.line', 'disassembly_id', string='Piezas que salen', copy=True)
    state = fields.Selection([('draft', 'Borrador'), ('done', 'Hecho'), ('cancel', 'Cancelado')],
                             default='draft', tracking=True)
    date_done = fields.Datetime(string='Fecha', readonly=True, copy=False)
    move_ids = fields.Many2many('stock.move', string='Movimientos', readonly=True, copy=False)
    piece_lot_ids = fields.Many2many('stock.lot', string='Lotes de las piezas', compute='_compute_piece_lots')

    @api.depends('product_id')
    def _compute_cost_total(self):
        for record in self:
            record.cost_total = record.product_id.standard_price

    @api.depends('line_ids.lot_ids')
    def _compute_piece_lots(self):
        for record in self:
            record.piece_lot_ids = record.line_ids.lot_ids

    @api.onchange('bom_id')
    def _onchange_bom_id(self):
        if self.bom_id and not self.line_ids:
            self.line_ids = [Command.create({'product_id': bl.product_id.id, 'quantity': bl.product_qty})
                             for bl in self.bom_id.bom_line_ids]

    def action_load_bom(self):
        for record in self.filtered(lambda r: r.bom_id and r.state == 'draft'):
            record.line_ids.unlink()
            record.line_ids = [Command.create({'product_id': bl.product_id.id, 'quantity': bl.product_qty})
                               for bl in record.bom_id.bom_line_ids]
        return True

    def action_save_bom(self):
        """Guarda las piezas indicadas como LdM de despiece del modelo (plantilla
        para la próxima vez)."""
        self.ensure_one()
        if not self.line_ids:
            raise UserError('Añade las piezas.')
        self.bom_id = self.env['mrp.bom'].create({
            'product_tmpl_id': self.product_id.product_tmpl_id.id,
            'product_id': self.product_id.id,
            'code': 'Despiece',
            'type': 'normal',
            'product_qty': 1,
            'company_id': self.company_id.id,
            'bom_line_ids': [Command.create({'product_id': line.product_id.id, 'product_qty': line.quantity})
                             for line in self.line_ids],
        })
        return True

    def _weights(self):
        weights = {}
        for line in self.line_ids:
            base = line.product_id.lst_price if self.allocation == 'price' else 1.0
            weights[line.id] = (base or 0.0) * line.quantity
        if not sum(weights.values()):
            weights = {line.id: line.quantity for line in self.line_ids}
        return weights

    def action_done(self):
        if not self.env.user.has_group('repair_security.group_repair_manager'):
            raise AccessError('Solo los responsables del SAT pueden validar un despiece.')
        for record in self:
            record._do_disassembly()
        return True

    def _do_disassembly(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError('Este despiece ya está hecho.')
        if not self.line_ids:
            raise UserError('Indica las piezas que salen del equipo.')
        if self.product_id.tracking != 'none' and not self.lot_id:
            raise UserError('Indica el nº de serie del equipo que se despieza.')
        for line in self.line_ids:
            product = line.product_id
            if product.tracking == 'none':
                raise UserError('Las piezas sin nº de serie solo pueden ser nuevas: quita %s' % product.display_name)
            names = [name.strip() for name in (line.serial or '').replace(',', '\n').splitlines() if name.strip()]
            if line.quantity <= 0:
                raise UserError('La cantidad de %s debe ser mayor que cero.' % product.display_name)
            if product.tracking == 'serial' and (line.quantity != int(line.quantity) or len(names) != line.quantity):
                raise UserError('Indica un nº de serie por unidad de %s.' % product.display_name)
            if product.tracking == 'lot' and len(names) != 1:
                raise UserError('Indica un lote para %s.' % product.display_name)
            if len(names) != len(set(names)):
                raise UserError('No repitas números de serie en %s.' % product.display_name)
        Quant = self.env['stock.quant'].sudo()
        domain = [('product_id', '=', self.product_id.id), ('location_id', '=', self.location_id.id),
                  ('lot_id', '=', self.lot_id.id or False), ('quantity', '>', 0)]
        if Quant.search_count(domain + [('owner_id', '!=', False)]):
            raise UserError('Solo se pueden despiezar equipos nuestros')
        available = sum(Quant.search(domain + [('owner_id', '=', False)]).mapped('quantity')) - sum(
            Quant.search(domain + [('owner_id', '=', False)]).mapped('reserved_quantity'))
        if available < 1:
            raise UserError('El equipo %s no está en stock en %s.' % (self.lot_id.name or self.product_id.display_name,
                                                                       self.location_id.display_name))
        if self.name == 'Nuevo':
            self.name = self.env['ir.sequence'].next_by_code('rms.disassembly') or 'DSP'
        scrap = self.env['stock.location']._rms_disassembly_location(self.company_id)
        second_hand = self.env['product.state'].search([('code', '=', 'second_hand')], limit=1)
        Move = self.env['stock.move']
        # 1) El equipo sale del stock (se valora a su coste).
        out = Move.create({
            'product_id': self.product_id.id, 'product_uom': self.product_id.uom_id.id, 'product_uom_qty': 1,
            'location_id': self.location_id.id, 'location_dest_id': scrap.id, 'company_id': self.company_id.id,
            'origin': self.name,
            'move_line_ids': [Command.create({
                'product_id': self.product_id.id, 'product_uom_id': self.product_id.uom_id.id, 'quantity': 1,
                'lot_id': self.lot_id.id, 'location_id': self.location_id.id, 'location_dest_id': scrap.id,
                'company_id': self.company_id.id})],
        })
        out._action_confirm()
        out.picked = True
        out._action_done()
        # 2) Las piezas entran como 2ª mano con el coste repartido.
        weights = self._weights()
        total_weight = sum(weights.values()) or 1.0
        moves = out
        Lot = self.env['stock.lot']
        for line in self.line_ids:
            unit_cost = self.cost_total * weights[line.id] / total_weight / line.quantity
            line.cost_unit = unit_cost
            product = line.product_id
            names = [name.strip() for name in line.serial.replace(',', '\n').splitlines() if name.strip()]
            ml_vals = []
            for name in names:
                lot = Lot.create({'product_id': product.id, 'name': name, 'company_id': self.company_id.id,
                                  'product_state_id': second_hand.id, 'rms_origin_disassembly_id': self.id,
                                  'rms_origin_lot_id': self.lot_id.id})
                ml_vals.append((lot, 1.0 if product.tracking == 'serial' else line.quantity))
            move = Move.create({
                'product_id': product.id, 'product_uom': product.uom_id.id, 'product_uom_qty': line.quantity,
                'location_id': scrap.id, 'location_dest_id': self.location_id.id, 'company_id': self.company_id.id,
                'origin': self.name, 'price_unit': unit_cost,
                'move_line_ids': [Command.create({
                    'product_id': product.id, 'product_uom_id': product.uom_id.id, 'quantity': qty,
                    'lot_id': lot.id, 'location_id': scrap.id, 'location_dest_id': self.location_id.id,
                    'company_id': self.company_id.id}) for lot, qty in ml_vals],
            })
            move._action_confirm()
            move.picked = True
            move._action_done()
            # Odoo 19 valora las entradas sin compra al coste del producto; el
            # coste repartido se fija con el "valor manual" estándar del movimiento.
            move.sudo().value_manual = unit_cost * line.quantity
            line.lot_ids = [Command.set([lot.id for lot, _qty in ml_vals if lot])]
            moves |= move
        self.write({'state': 'done', 'date_done': fields.Datetime.now(), 'move_ids': [Command.set(moves.ids)]})
        return True

    def action_print_labels(self):
        self.ensure_one()
        if not self.piece_lot_ids:
            raise UserError('Las piezas de este despiece no llevan lote (no se siguen por lote/nº de serie).')
        return self.env.ref('rms_stock_lot_label_print.action_report_lot_label_10x5').report_action(
            self.piece_lot_ids, config=False)


class RmsDisassemblyLine(models.Model):
    _name = 'rms.disassembly.line'
    _description = 'Pieza que sale de un despiece'

    disassembly_id = fields.Many2one('rms.disassembly', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Pieza', required=True,
                                 domain="[('is_storable', '=', True)]")
    tracking = fields.Selection(related='product_id.tracking', string='Seguimiento')
    quantity = fields.Float(string='Cantidad', default=1.0, required=True)
    serial = fields.Text(string='Nº de serie o lote',
                         help='Indica un nº de serie de fábrica por unidad, separado por comas o líneas; para lote, indica uno.')
    cost_unit = fields.Float(string='Coste unitario asignado', readonly=True, digits='Product Price')
    lot_ids = fields.Many2many('stock.lot', string='Lotes creados', readonly=True)


class StockLot(models.Model):
    _inherit = 'stock.lot'

    rms_origin_disassembly_id = fields.Many2one('rms.disassembly', string='Despiece de origen', copy=False, readonly=True)
    rms_origin_lot_id = fields.Many2one('stock.lot', string='Nº de serie de origen', copy=False, readonly=True)
    rms_origin_product_id = fields.Many2one(related='rms_origin_disassembly_id.product_id', string='Equipo de origen')

    def action_rms_disassemble(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': 'Despiezar', 'res_model': 'rms.disassembly',
            'view_mode': 'form', 'target': 'current',
            'context': {'default_product_id': self.product_id.id, 'default_lot_id': self.id,
                        'default_company_id': self.company_id.id or self.env.company.id},
        }
