# -*- coding: utf-8 -*-
from odoo import Command, api, fields, models
from odoo.exceptions import UserError

SAT_STAGES = [
    ('received', 'Recibido'),
    ('diagnosis', 'Diagnóstico'),
    ('quoted', 'Presupuesto enviado'),
    ('accepted', 'Aceptado'),
    ('repair', 'En reparación'),
    ('factory', 'En fábrica'),
    ('ready', 'Listo'),
    ('delivered', 'Entregado / Enviado'),
    ('cancel', 'Cancelado'),
]
# Estado de Odoo (repair) -> fase del SAT cuando cambia.
STATE_TO_STAGE = {'confirmed': 'accepted', 'under_repair': 'repair', 'done': 'ready', 'cancel': 'cancel',
                  'draft': 'received'}
LATE_DAYS_PARAM = 'rms_repair_sat.late_days'
USED_FACTOR_PARAM = 'rms_repair_sat.used_price_factor'


class RepairOrder(models.Model):
    _inherit = 'repair.order'

    rms_site = fields.Selection([('madrid', 'Madrid'), ('sevilla', 'Sevilla')], string='Sede', tracking=True)
    rms_entry_way = fields.Selection([('hand', 'En mano'), ('shipping', 'Por envío')], string='Cómo llega',
                                     default='hand')
    rms_fault = fields.Text(string='Avería que indica el cliente')
    rms_accessories = fields.Text(string='Accesorios entregados')
    rms_serial_in = fields.Char(string='Nº de serie del equipo',
                                help='Si el nº de serie no existe en Odoo, se da de alta al registrar la entrada.')
    rms_stage = fields.Selection(SAT_STAGES, string='Fase SAT', default='received', required=True, tracking=True,
                                 group_expand='_group_expand_rms_stage', index=True)
    rms_stage_date = fields.Datetime(string='En esta fase desde', default=fields.Datetime.now, copy=False)
    rms_entry_date = fields.Datetime(string='Entrada', copy=False, readonly=True)
    rms_days_stage = fields.Integer(string='Días en la fase', compute='_compute_rms_days')
    rms_days_total = fields.Integer(string='Días en el SAT', compute='_compute_rms_days')
    rms_late = fields.Boolean(string='Atascada', compute='_compute_rms_days')
    rms_entry_move_id = fields.Many2one('stock.move', string='Movimiento de entrada', copy=False, readonly=True)
    rms_exit_move_id = fields.Many2one('stock.move', string='Movimiento de salida', copy=False, readonly=True)
    # Envío a fábrica (RA)
    rms_factory_partner_id = fields.Many2one('res.partner', string='Fábrica / fabricante', copy=False, tracking=True)
    rms_rma_number = fields.Char(string='Nº RMA del fabricante', copy=False, tracking=True)
    rms_factory_sent_date = fields.Date(string='Enviado a fábrica', copy=False, readonly=True)
    rms_factory_back_date = fields.Date(string='Vuelta de fábrica', copy=False, readonly=True)
    rms_factory_days = fields.Integer(string='Días en fábrica', compute='_compute_rms_days')
    rms_in_sat = fields.Boolean(string='Equipo en el SAT', copy=False, readonly=True)
    rms_parts_choice = fields.Selection([('new', 'Piezas nuevas'), ('used', 'Piezas de 2ª mano')],
                                        string='Opción elegida', copy=False, tracking=True)

    @api.model
    def _group_expand_rms_stage(self, values, domain):
        return [key for key, _label in SAT_STAGES]

    @api.depends('rms_stage_date', 'rms_entry_date', 'rms_factory_sent_date', 'rms_factory_back_date', 'rms_stage')
    def _compute_rms_days(self):
        now = fields.Datetime.now()
        today = fields.Date.context_today(self)
        late = int(self.env['ir.config_parameter'].sudo().get_param(LATE_DAYS_PARAM, '7') or 7)
        for repair in self:
            repair.rms_days_stage = (now - repair.rms_stage_date).days if repair.rms_stage_date else 0
            start = repair.rms_entry_date or repair.create_date
            repair.rms_days_total = (now - start).days if start else 0
            if repair.rms_factory_sent_date:
                end = repair.rms_factory_back_date or today
                repair.rms_factory_days = (end - repair.rms_factory_sent_date).days
            else:
                repair.rms_factory_days = 0
            repair.rms_late = repair.rms_stage not in ('delivered', 'cancel') and repair.rms_days_stage > late

    # ------------------------------------------------------------------
    # Sede -> tipo de operación SAT (piezas del almacén, equipo en SAT)
    # ------------------------------------------------------------------
    def _rms_warehouse(self):
        self.ensure_one()
        if not self.rms_site:
            return self.env['stock.warehouse']
        digit = '1' if self.rms_site == 'madrid' else '7'
        warehouses = self.env['stock.warehouse'].search([('company_id', '=', self.company_id.id)])
        return warehouses.filtered(lambda w: (w.code or '').strip().endswith(digit) and w.rms_sat_location_id)[:1]

    def _rms_apply_site(self):
        for repair in self.filtered(lambda r: r.rms_site and r.state == 'draft'):
            warehouse = repair._rms_warehouse()
            if warehouse.rms_sat_picking_type_id and repair.picking_type_id != warehouse.rms_sat_picking_type_id:
                repair.picking_type_id = warehouse.rms_sat_picking_type_id

    @api.model_create_multi
    def create(self, vals_list):
        repairs = super().create(vals_list)
        repairs._rms_apply_site()
        return repairs

    def write(self, vals):
        if 'rms_stage' in vals:
            vals = dict(vals, rms_stage_date=fields.Datetime.now())
        res = super().write(vals)
        if 'rms_site' in vals:
            self._rms_apply_site()
        if 'state' in vals and STATE_TO_STAGE.get(vals['state']):
            stage = STATE_TO_STAGE[vals['state']]
            # No retroceder la fase (p. ej. confirmar estando "En fábrica").
            order = [key for key, _label in SAT_STAGES]
            todo = self.filtered(lambda r: r.rms_stage != stage and (
                stage in ('cancel', 'received') or order.index(stage) > order.index(r.rms_stage)
                or r.rms_stage == 'factory'))
            if todo:
                super(RepairOrder, todo).write({'rms_stage': stage, 'rms_stage_date': fields.Datetime.now()})
        return res

    # ------------------------------------------------------------------
    # Movimientos del equipo del CLIENTE: propietario = cliente y
    # restrict_partner_id = cliente -> fuera de la valoración propia.
    # ------------------------------------------------------------------
    def _rms_customer_move(self, location_src, location_dest, label):
        self.ensure_one()
        if not self.product_id or not self.partner_id:
            raise UserError('Indica el cliente y el equipo.')
        move = self.env['stock.move'].sudo().create({
            'product_id': self.product_id.id,
            'product_uom': self.product_id.uom_id.id,
            'product_uom_qty': self.product_qty or 1.0,
            'location_id': location_src.id,
            'location_dest_id': location_dest.id,
            'partner_id': self.partner_id.id,
            'restrict_partner_id': self.partner_id.id,
            'company_id': self.company_id.id,
            'origin': '%s · %s' % (self.name, label),
            'move_line_ids': [Command.create({
                'product_id': self.product_id.id,
                'product_uom_id': self.product_id.uom_id.id,
                'quantity': self.product_qty or 1.0,
                'lot_id': self.lot_id.id,
                'owner_id': self.partner_id.id,
                'location_id': location_src.id,
                'location_dest_id': location_dest.id,
                'company_id': self.company_id.id,
            })],
        })
        move._action_confirm()
        move.picked = True
        move._action_done()
        return move

    def _rms_sat_locations(self):
        self.ensure_one()
        warehouse = self._rms_warehouse()
        if not warehouse.rms_sat_location_id:
            raise UserError('Falta la sede o no están creadas las ubicaciones del SAT '
                            '(SAT > Configuración > Preparar ubicaciones SAT).')
        return warehouse

    def action_rms_register_entry(self):
        """Entrada del equipo del cliente en el SAT (sin valoración propia)."""
        customers = self.env.ref('stock.stock_location_customers')
        for repair in self:
            if repair.rms_in_sat:
                continue
            warehouse = repair._rms_sat_locations()
            if repair.product_id.tracking != 'none' and not repair.lot_id:
                serial = (repair.rms_serial_in or '').strip()
                if not serial:
                    raise UserError('Escribe el nº de serie del equipo.')
                Lot = self.env['stock.lot'].sudo()
                lot = Lot.search([('product_id', '=', repair.product_id.id), ('name', '=', serial),
                                  ('company_id', 'in', [repair.company_id.id, False])], limit=1)
                repair.lot_id = lot or Lot.create({'product_id': repair.product_id.id, 'name': serial,
                                                   'company_id': repair.company_id.id})
            repair.rms_entry_move_id = repair._rms_customer_move(customers, warehouse.rms_sat_location_id, 'Entrada SAT')
            repair.write({'rms_in_sat': True, 'rms_entry_date': fields.Datetime.now(), 'rms_stage': 'received'})
        return True

    def action_rms_deliver(self):
        """Devuelve el equipo al cliente (en mano o por envío)."""
        customers = self.env.ref('stock.stock_location_customers')
        for repair in self:
            if not repair.rms_in_sat:
                raise UserError('El equipo de %s no está en el SAT.' % repair.name)
            if repair.rms_stage == 'factory':
                raise UserError('El equipo de %s sigue en fábrica.' % repair.name)
            warehouse = repair._rms_sat_locations()
            repair.rms_exit_move_id = repair._rms_customer_move(warehouse.rms_sat_location_id, customers, 'Salida SAT')
            repair.write({'rms_in_sat': False, 'rms_stage': 'delivered'})
        return True

    def action_rms_send_factory(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': 'Enviar a fábrica', 'res_model': 'rms.repair.factory.wizard',
            'view_mode': 'form', 'target': 'new', 'context': {'default_repair_id': self.id},
        }

    def _rms_send_to_factory(self, partner, rma, date):
        self.ensure_one()
        if not self.rms_in_sat:
            raise UserError('Registra antes la entrada del equipo en el SAT.')
        warehouse = self._rms_sat_locations()
        self._rms_customer_move(warehouse.rms_sat_location_id, warehouse.rms_sat_factory_location_id, 'Enviado a fábrica')
        self.write({'rms_factory_partner_id': partner.id, 'rms_rma_number': rma, 'rms_factory_sent_date': date,
                    'rms_factory_back_date': False, 'rms_stage': 'factory'})

    def action_rms_back_from_factory(self):
        for repair in self.filtered(lambda r: r.rms_stage == 'factory'):
            warehouse = repair._rms_sat_locations()
            repair._rms_customer_move(warehouse.rms_sat_factory_location_id, warehouse.rms_sat_location_id,
                                      'Vuelta de fábrica')
            repair.write({'rms_factory_back_date': fields.Date.context_today(repair),
                          'rms_stage': 'ready' if repair.state == 'done' else 'repair'})
        return True

    def action_rms_print_label(self):
        lots = self.lot_id
        if not lots:
            raise UserError('Esta reparación no tiene nº de serie.')
        return self.env.ref('rms_stock_lot_label_print.action_report_lot_label_10x5').report_action(lots, config=False)

    # ------------------------------------------------------------------
    # Fases ligadas a Odoo y corrección del propietario al terminar
    # ------------------------------------------------------------------
    def action_create_sale_order(self):
        res = super().action_create_sale_order()
        self.filtered(lambda r: r.rms_stage in ('received', 'diagnosis')).write({'rms_stage': 'quoted'})
        return res

    def action_repair_done(self):
        pairs = [(r.product_id.id, r.lot_id.id or False, r.partner_id.id, r.product_location_src_id.id)
                 for r in self if r.rms_in_sat and r.product_id and r.partner_id and r.product_location_src_id]
        return super(RepairOrder, self.with_context(rms_sat_owner_pairs=pairs)).action_repair_done()

    # ------------------------------------------------------------------
    # Alternativa con piezas de 2ª mano (sección opcional del presupuesto)
    # ------------------------------------------------------------------
    def _rms_used_lot(self, product, location):
        quant = self.env['stock.quant'].sudo().search([
            ('product_id', '=', product.id), ('location_id', 'child_of', location.id),
            ('quantity', '>', 0), ('lot_id.product_state_id.code', '=', 'second_hand')], limit=1)
        return quant.lot_id

    def _rms_used_price(self, product, lot):
        if lot and lot.custom_price:
            return lot.custom_price
        factor = float(self.env['ir.config_parameter'].sudo().get_param(USED_FACTOR_PARAM, '0.5') or 0.5)
        return product.lst_price * factor

    def action_rms_add_used_alternative(self):
        """Añade al presupuesto una sección OPCIONAL "Alternativa con piezas de
        2ª mano" con las mismas piezas a precio de 2ª mano (cantidad 0, como las
        opcionales de Odoo: el cliente la elige)."""
        for repair in self:
            order = repair.sale_order_id
            if not order:
                raise UserError('Crea antes el presupuesto de la reparación.')
            if order.state not in ('draft', 'sent'):
                raise UserError('El presupuesto ya está confirmado.')
            lines = order.order_line.filtered(lambda l: l.move_ids.filtered(lambda m: m.repair_id == repair
                                                                               and m.repair_line_type == 'add'))
            if not lines:
                raise UserError('La reparación no tiene piezas en el presupuesto.')
            old = order.order_line.filtered('rms_used_alternative_of_id')
            old.unlink()
            order.order_line.filtered(lambda l: l.display_type == 'line_section' and l.rms_used_section).unlink()
            sequence = max(order.order_line.mapped('sequence') or [10]) + 10
            vals = [{'order_id': order.id, 'display_type': 'line_section', 'is_optional': True,
                     'rms_used_section': True, 'name': 'Alternativa con piezas de 2ª mano', 'sequence': sequence,
                     'product_uom_qty': 0}]
            for index, line in enumerate(lines, 1):
                lot = repair._rms_used_lot(line.product_id, repair.location_id)
                vals.append({
                    'order_id': order.id, 'product_id': line.product_id.id, 'product_uom_qty': 0,
                    'name': '%s (2ª mano%s)' % (line.product_id.display_name, ' · %s' % lot.name if lot else ''),
                    'price_unit': 0.0 if repair.under_warranty else repair._rms_used_price(line.product_id, lot),
                    'sequence': sequence + index, 'rms_used_alternative_of_id': line.id,
                    'rms_used_lot_id': lot.id,
                })
            self.env['sale.order.line'].create(vals)
        return True

    def action_rms_choose_used(self):
        """El cliente elige la alternativa de 2ª mano: esas líneas pasan a la
        cantidad de la reparación, las de piezas nuevas a 0, y las piezas de la
        reparación se reservan del lote de 2ª mano si hay."""
        for repair in self:
            order = repair.sale_order_id
            alternatives = order.order_line.filtered('rms_used_alternative_of_id')
            if not alternatives:
                raise UserError('Añade antes la alternativa de 2ª mano al presupuesto.')
            for alt in alternatives:
                original = alt.rms_used_alternative_of_id
                moves = original.move_ids.filtered(lambda m: m.repair_id == repair and m.state not in ('done', 'cancel'))
                qty = sum(moves.mapped('product_uom_qty')) or original.product_uom_qty
                moves.write({'sale_line_id': alt.id})
                price = alt.price_unit
                vals = {'product_uom_qty': qty}
                if alt.rms_used_lot_id and qty == 1 and not alt.serial_ids:
                    # Nº de serie de 2ª mano en la línea (rms_product_state): el
                    # presupuesto muestra "2ª Mano" y la venta queda trazada.
                    vals['serial_ids'] = [Command.create({'lot_id': alt.rms_used_lot_id.id, 'price_unit': price})]
                alt.write(vals)
                alt.price_unit = price  # Odoo recalcula el precio al cambiar la cantidad
                original.product_uom_qty = 0
                if alt.rms_used_lot_id:
                    for move in moves:
                        move._do_unreserve()
                        move.move_line_ids.unlink()
                        self.env['stock.move.line'].create({
                            'move_id': move.id, 'product_id': move.product_id.id,
                            'product_uom_id': move.product_uom.id, 'quantity': move.product_uom_qty,
                            'lot_id': alt.rms_used_lot_id.id, 'location_id': move.location_id.id,
                            'location_dest_id': move.location_dest_id.id, 'company_id': move.company_id.id})
            repair.write({'rms_parts_choice': 'used', 'rms_stage': 'accepted'})
        return True

    def action_rms_choose_new(self):
        self.write({'rms_parts_choice': 'new', 'rms_stage': 'accepted'})
        return True
