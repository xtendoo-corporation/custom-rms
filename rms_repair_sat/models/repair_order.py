# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta

from odoo import Command, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import html_sanitize

SAT_STAGES = [
    ('received', 'Recibido'), ('diagnosis', 'En diagnóstico'),
    ('quoted', 'Presupuesto enviado'), ('waiting_part', 'Esperando pieza'),
    ('factory', 'En fábrica'), ('repair', 'En reparación'),
    ('ready', 'Listo para recoger'), ('delivered', 'Entregado'),
    ('uncollected', 'Pendiente de recoger'),
]
STATE_TO_STAGE = {'confirmed': 'repair', 'under_repair': 'repair', 'done': 'ready',
                  'cancel': 'cancel', 'draft': 'received'}


class RepairOrder(models.Model):
    _inherit = 'repair.order'

    partner_id = fields.Many2one(required=False)
    rms_owner_type = fields.Selection([('customer', 'Del cliente'), ('company', 'Nuestro')],
                                      string='Propietario', required=True, default='customer', tracking=True)
    rms_contact_id = fields.Many2one('res.partner', string='Contacto', domain="[('id', 'child_of', partner_id)]")
    rms_contact_phone = fields.Char(related='rms_contact_id.phone', string='Teléfono')
    rms_contact_email = fields.Char(related='rms_contact_id.email', string='Correo')
    rms_tracking_ref = fields.Char(string='Nº de envío')
    rms_delivery_way = fields.Selection([('hand', 'En mano'), ('courier', 'Transportista')],
                                         string='Forma de entrega', default='hand')
    rms_delivery_tracking_ref = fields.Char(string='Nº de envío de entrega')
    rms_accessory_ids = fields.Many2many('rms.repair.accessory', string='Accesorios')
    rms_intermittent = fields.Selection([('constant', 'Constante'), ('intermittent', 'Intermitente')], string='Avería')
    rms_purchase_ref = fields.Char(string='Factura de compra')
    rms_needed_by = fields.Date(string='Lo necesita para')
    rms_backup_done = fields.Boolean(string='Cliente ha guardado copia de shows/configuración')
    rms_currency_id = fields.Many2one('res.currency', related='company_id.currency_id')
    rms_max_amount = fields.Monetary(string='Importe máximo sin consultar', currency_field='rms_currency_id')
    rms_received_by = fields.Many2one('res.users', string='Recibido por', default=lambda self: self.env.user, readonly=True)
    rms_photo_count = fields.Integer(string='Fotos', compute='_compute_rms_photo_count')
    rms_sale_date = fields.Date(string='Fecha de venta', compute='_compute_rms_warranty', store=True)
    rms_warranty_end = fields.Date(string='Fin de garantía', compute='_compute_rms_warranty', store=True)
    rms_warranty_source = fields.Selection([('product', 'Producto'), ('brand', 'Marca'), ('default', 'Por defecto')],
                                            string='Origen de garantía', compute='_compute_rms_warranty', store=True)
    rms_site = fields.Selection([('madrid', 'Madrid'), ('sevilla', 'Sevilla')], string='Sede', tracking=True)
    rms_entry_way = fields.Selection([('hand', 'En mano'), ('courier', 'Mensajería'), ('pickup', 'Recogida nuestra')], string='Cómo llega',
                                     default='hand')
    rms_fault = fields.Text(string='Avería que indica el cliente')
    rms_accessories = fields.Text(string='Notas de accesorios')
    rms_serial_in = fields.Char(string='Nº de serie del equipo',
                                help='Si el nº de serie no existe en Odoo, se da de alta al registrar la entrada.')
    rms_stage = fields.Selection(SAT_STAGES + [('cancel', 'Cancelado')], string='Fase SAT', default='received', required=True, tracking=True,
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

    rms_factory_tracking_ref = fields.Char(string='Nº de envío a fábrica', copy=False)
    rms_factory_shipping_cost = fields.Monetary(string='Coste del porte', currency_field='rms_currency_id', copy=False)
    rms_factory_note = fields.Text(string='Nota de fábrica', copy=False)
    rms_factory_credit_ref = fields.Char(string='Nº de abono', copy=False)
    rms_factory_result = fields.Selection([('repaired', 'Reparado'), ('replaced', 'Sustituido por otro'),
                                           ('credited', 'Abonado por la fábrica')], string='Resultado de fábrica', copy=False)
    rms_factory_bill_ids = fields.Many2many('account.move', string='Facturas de fábrica', domain="[('move_type', '=', 'in_invoice')]")
    rms_swap_done = fields.Boolean(string='Cambio realizado', copy=False, readonly=True)
    rms_swap_date = fields.Date(string='Fecha de cambio', copy=False, readonly=True)
    rms_swap_lot_id = fields.Many2one('stock.lot', string='Nº de serie entregado', copy=False, readonly=True)
    rms_original_lot_id = fields.Many2one('stock.lot', string='Nº de serie original', copy=False, readonly=True)
    rms_original_partner_id = fields.Many2one('res.partner', string='Cliente original', copy=False, readonly=True)
    rms_swap_picking_id = fields.Many2one('stock.picking', string='Entrega del cambio', copy=False, readonly=True)
    rms_swap_note = fields.Text(string='Nota del cambio', copy=False)
    rms_labour_mode = fields.Selection([('hourly', 'Por horas'), ('fixed', 'Precio cerrado')], string='Mano de obra', default='hourly')
    rms_labour_hours = fields.Float(string='Horas de taller')
    rms_fixed_price_id = fields.Many2one('rms.repair.fixed.price', string='Tipo de reparación')
    rms_labour_service_id = fields.Many2one('repair.service', string='Servicio de mano de obra', copy=False)
    rms_labour_line_id = fields.Many2one('sale.order.line', string='Línea de mano de obra', copy=False)
    rms_factory_bill_line_id = fields.Many2one('sale.order.line', string='Línea de fábrica', copy=False)
    rms_sale_order_state = fields.Selection(related='sale_order_id.state')
    rms_rejected_date = fields.Date(string='Fecha de rechazo', copy=False)
    rms_accepted_amount = fields.Monetary(string='Importe aceptado', currency_field='rms_currency_id', copy=False)
    rms_has_accepted_amount = fields.Boolean(string='Presupuesto aceptado', copy=False)
    rms_needs_reapproval = fields.Boolean(string='Necesita nueva aceptación', compute='_compute_rms_needs_reapproval')
    rms_reapproved = fields.Boolean(string='Ampliación aceptada', tracking=True, copy=False)

    @api.depends('sale_order_id.amount_total', 'rms_accepted_amount', 'rms_has_accepted_amount', 'rms_max_amount')
    def _compute_rms_needs_reapproval(self):
        for repair in self:
            repair.rms_needs_reapproval = bool(repair.rms_has_accepted_amount and repair.sale_order_id and
                repair.sale_order_id.amount_total > repair.rms_accepted_amount + repair.rms_max_amount)

    @api.model
    def _group_expand_rms_stage(self, values, domain):
        return [key for key, _label in SAT_STAGES]

    @api.depends('rms_stage_date', 'rms_entry_date', 'rms_factory_sent_date', 'rms_factory_back_date', 'rms_stage')
    def _compute_rms_days(self):
        now = fields.Datetime.now()
        today = fields.Date.context_today(self)
        limits = {r.stage: r.days for r in self.env['rms.repair.stage.limit'].sudo().search([])}
        for repair in self:
            repair.rms_days_stage = (now - repair.rms_stage_date).days if repair.rms_stage_date else 0
            start = repair.rms_entry_date or repair.create_date
            repair.rms_days_total = (now - start).days if start else 0
            if repair.rms_factory_sent_date:
                end = repair.rms_factory_back_date or today
                repair.rms_factory_days = (end - repair.rms_factory_sent_date).days
            else:
                repair.rms_factory_days = 0
            limit = limits.get(repair.rms_stage, 0)
            repair.rms_late = bool(limit and repair.rms_days_stage > limit)

    def _compute_rms_photo_count(self):
        for repair in self:
            repair.rms_photo_count = self.env['ir.attachment'].search_count([
                ('res_model', '=', 'repair.order'), ('res_id', '=', repair.id), ('mimetype', '=like', 'image/%')]) if repair.id else 0

    @api.depends('lot_id', 'product_id', 'product_id.product_tmpl_id.warranty',
                 'product_id.product_tmpl_id.warranty_type', 'product_id.categ_id',
                 'product_id.categ_id.rms_warranty_months', 'product_id.categ_id.parent_id.rms_warranty_months', 'company_id')
    def _compute_rms_warranty(self):
        MoveLine = self.env['stock.move.line'].sudo()
        for repair in self:
            repair.rms_sale_date = repair.rms_warranty_end = repair.rms_warranty_source = False
            if not repair.lot_id:
                continue
            line = MoveLine.search([('lot_id', '=', repair.lot_id.id), ('state', '=', 'done'),
                                    ('location_id.usage', '=', 'internal'), ('location_dest_id.usage', '=', 'customer'),
                                    ('company_id', 'in', self.env.companies.ids)], order='date desc, id desc', limit=1)
            if not line:
                continue
            sale_date = fields.Date.to_date(line.date)
            product = repair.product_id.product_tmpl_id
            category = repair.product_id.categ_id
            while category and not category.rms_warranty_months:
                category = category.parent_id
            if product.warranty > 0:
                unit = {'day': 'days', 'week': 'weeks', 'month': 'months', 'year': 'years'}.get(product.warranty_type, 'months')
                duration = {unit: product.warranty}
                source = 'product'
            elif category:
                duration, source = {'months': category.rms_warranty_months}, 'brand'
            else:
                months = int(self.env['ir.config_parameter'].sudo().get_param('rms_repair_sat.default_warranty_months', '24'))
                duration, source = {'months': months}, 'default'
            repair.rms_sale_date = sale_date
            repair.rms_warranty_end = sale_date + relativedelta(**duration)
            repair.rms_warranty_source = source

    @api.onchange('lot_id')
    def _onchange_rms_lot_warranty(self):
        for repair in self:
            repair._compute_rms_warranty()
            repair.under_warranty = bool(repair.rms_warranty_end and fields.Date.context_today(repair) <= repair.rms_warranty_end)

    def _rms_receipt_terms(self):
        """Condiciones del resguardo (HTML de los ajustes del SAT), saneadas."""
        terms = self.env['ir.config_parameter'].sudo().get_param('rms_repair_sat.receipt_terms', '')
        return html_sanitize(terms) or ''

    def _rms_validate_entry(self):
        self.ensure_one()
        self.invalidate_recordset(['rms_photo_count'])
        missing = []
        if self.rms_owner_type == 'customer' and not self.partner_id:
            missing.append('cliente')
        for value, label in [(self.rms_contact_id, 'contacto'), (self.product_id, 'equipo'),
                             (self.lot_id or (self.rms_serial_in or '').strip(), 'nº de serie'),
                             (self.rms_owner_type, 'propietario'), (self.rms_entry_way, 'forma de entrada'),
                             ((self.rms_fault or '').strip(), 'avería'), (self.rms_accessory_ids, 'accesorios'),
                             (self.rms_photo_count, 'foto')]:
            if not value:
                missing.append(label)
        if self.rms_entry_way == 'courier' and not (self.rms_tracking_ref or '').strip():
            missing.append('nº de envío')
        if missing:
            raise UserError('Faltan datos para registrar la entrada: %s.' % ', '.join(missing))

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
            order = [key for key, _label in SAT_STAGES] + ['cancel']
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
        if not self.product_id or (self.rms_owner_type == 'customer' and not self.partner_id):
            raise UserError('Indica el cliente y el equipo.')
        move = self.env['stock.move'].sudo().create({
            'product_id': self.product_id.id,
            'product_uom': self.product_id.uom_id.id,
            'product_uom_qty': self.product_qty or 1.0,
            'location_id': location_src.id,
            'location_dest_id': location_dest.id,
            'partner_id': self.partner_id.id,
            'restrict_partner_id': self.partner_id.id if self.rms_owner_type == 'customer' else False,
            'company_id': self.company_id.id,
            'origin': '%s · %s' % (self.name, label),
            'move_line_ids': [Command.create({
                'product_id': self.product_id.id,
                'product_uom_id': self.product_id.uom_id.id,
                'quantity': self.product_qty or 1.0,
                'lot_id': self.lot_id.id,
                'owner_id': self.partner_id.id if self.rms_owner_type == 'customer' else False,
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
            repair._rms_validate_entry()
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
                repair._onchange_rms_lot_warranty()
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
            source = warehouse.rms_ra_location_id if repair.product_location_src_id == warehouse.rms_ra_location_id else warehouse.rms_sat_location_id
            repair.rms_exit_move_id = repair._rms_customer_move(source, customers, 'Salida SAT')
            repair.write({'rms_in_sat': False, 'rms_stage': 'delivered'})
        return True

    def action_rms_send_factory(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': 'Enviar a fábrica', 'res_model': 'rms.repair.factory.wizard',
            'view_mode': 'form', 'target': 'new', 'context': {'default_repair_id': self.id},
        }

    def _rms_send_to_factory(self, partner, rma, date, tracking_ref=False, shipping_cost=0, note=False):
        self.ensure_one()
        if not self.rms_in_sat:
            raise UserError('Registra antes la entrada del equipo en el SAT.')
        warehouse = self._rms_sat_locations()
        source = warehouse.rms_ra_location_id if self.rms_swap_done and self.product_location_src_id == warehouse.rms_ra_location_id else warehouse.rms_sat_location_id
        self._rms_customer_move(source, warehouse.rms_sat_factory_location_id, 'Enviado a fábrica')
        self.write({'rms_factory_partner_id': partner.id, 'rms_rma_number': rma, 'rms_factory_sent_date': date,
                    'rms_factory_back_date': False, 'rms_factory_result': False, 'rms_factory_tracking_ref': tracking_ref,
                    'rms_factory_shipping_cost': shipping_cost, 'rms_factory_note': note, 'rms_stage': 'factory'})

    def action_rms_back_from_factory(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Vuelta de fábrica',
                'res_model': 'rms.repair.factory.return.wizard', 'view_mode': 'form', 'target': 'new',
                'context': {'default_repair_id': self.id}}

    def action_rms_swap(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Cambio en garantía',
                'res_model': 'rms.repair.swap.wizard', 'view_mode': 'form', 'target': 'new',
                'context': {'default_repair_id': self.id, 'default_product_id': self.product_id.id}}

    def action_rms_wait_part(self):
        self.write({'rms_stage': 'waiting_part'})

    def action_rms_part_received(self):
        self.write({'rms_stage': 'repair'})

    def _rms_draft_order(self):
        self.ensure_one()
        if not self.sale_order_id or self.sale_order_id.state not in ('draft', 'sent'):
            raise UserError('Hace falta un presupuesto en borrador o enviado.')
        return self.sale_order_id

    def action_rms_add_factory_bill(self):
        self.ensure_one()
        order = self._rms_draft_order()
        if self.under_warranty:
            raise UserError('No se repercute la factura de fábrica si está en garantía.')
        if not self.rms_factory_bill_ids or any(b.move_type != 'in_invoice' for b in self.rms_factory_bill_ids):
            raise UserError('Añade facturas de proveedor.')
        product = self.env.ref('rms_repair_sat.product_factory_repair')
        vals = {'order_id': order.id, 'product_id': product.id, 'product_uom_qty': 1,
                'name': 'Reparación en fábrica · RMA %s' % (self.rms_rma_number or '-'),
                'price_unit': sum(self.rms_factory_bill_ids.mapped('amount_untaxed'))}
        if self.rms_factory_bill_line_id and self.rms_factory_bill_line_id.order_id == order:
            self.rms_factory_bill_line_id.write(vals)
        else:
            self.rms_factory_bill_line_id = self.env['sale.order.line'].create(vals)
        self.rms_factory_bill_line_id._rms_clear_service_discounts()

    def action_rms_add_labour(self):
        self.ensure_one()
        order = self._rms_draft_order()
        if self.rms_labour_mode == 'fixed':
            if not self.rms_fixed_price_id:
                raise UserError('Elige un tipo de reparación.')
            product, qty, price = self.rms_fixed_price_id.product_id, 1, self.rms_fixed_price_id.price
        else:
            if self.rms_labour_hours <= 0:
                raise UserError('Indica las horas de taller.')
            product, qty = self.env.ref('rms_repair_sat.product_labour_hour'), self.rms_labour_hours
            price = product.lst_price
        service_vals = {'repair_id': self.id, 'product_id': product.id, 'product_uom_qty': qty,
                        'product_uom': product.uom_id.id}
        if self.rms_labour_service_id:
            self.rms_labour_service_id.write(service_vals)
        else:
            self.rms_labour_service_id = self.env['repair.service'].create(service_vals)
        vals = self.rms_labour_service_id._prepare_sale_order_line_vals(qty)
        vals['price_unit'] = 0 if self.under_warranty else price
        if self.rms_labour_line_id and self.rms_labour_line_id.order_id == order:
            self.rms_labour_line_id.write(vals)
        else:
            self.rms_labour_line_id = self.env['sale.order.line'].create(vals)
        self.rms_labour_line_id._rms_clear_service_discounts()

    def action_rms_send_quote(self):
        self.ensure_one()
        order = self._rms_draft_order()
        action = order.action_quotation_send()
        self.rms_stage = 'quoted'
        return action

    def action_rms_reject_quote(self):
        for repair in self:
            order = repair._rms_draft_order()
            order.action_cancel()
            repair.write({'rms_stage': 'uncollected', 'rms_rejected_date': fields.Date.context_today(repair)})

    def action_rms_reapprove(self):
        for repair in self:
            if not repair.rms_has_accepted_amount or not repair.sale_order_id:
                raise UserError('No hay un presupuesto aceptado.')
            repair.write({'rms_reapproved': True, 'rms_accepted_amount': repair.sale_order_id.amount_total})

    def action_rms_print_label(self):
        return self.env.ref('rms_repair_sat.action_report_label_equipment').report_action(self, config=False)

    # ------------------------------------------------------------------
    # Fases ligadas a Odoo y corrección del propietario al terminar
    # ------------------------------------------------------------------
    def action_create_sale_order(self):
        res = super().action_create_sale_order()
        self.filtered(lambda r: r.rms_stage in ('received', 'diagnosis')).write({'rms_stage': 'quoted'})
        for repair in self:
            lines = repair.sale_order_id.order_line.filtered(lambda line: line.move_ids.filtered(
                lambda move: move.repair_id == repair and move.repair_line_type == 'add'))
            lines._rms_apply_part_discounts()
        return res

    def action_repair_done(self):
        if any(repair.rms_needs_reapproval for repair in self):
            raise UserError('El presupuesto supera lo aceptado: pide una nueva aceptación al cliente.')
        pairs = [(r.product_id.id, r.lot_id.id or False, r.partner_id.id, r.product_location_src_id.id)
                 for r in self if r.rms_owner_type == 'customer' and r.rms_in_sat and r.product_id and r.partner_id and r.product_location_src_id]
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
        return product.lst_price

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
            untracked = lines.filtered(lambda line: line.product_id.tracking == 'none')
            lines = lines - untracked
            old = order.order_line.filtered('rms_used_alternative_of_id')
            old.unlink()
            order.order_line.filtered(lambda l: l.display_type == 'line_section' and l.rms_used_section).unlink()
            sequence = max(order.order_line.mapped('sequence') or [10]) + 10
            vals = [{'order_id': order.id, 'display_type': 'line_section', 'is_optional': True,
                     'rms_used_section': True, 'name': 'Alternativa con piezas de 2ª mano' + ((' (sin 2ª mano: %s)' % ', '.join(untracked.mapped('product_id.display_name'))) if untracked else ''), 'sequence': sequence,
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
            created = self.env['sale.order.line'].create(vals)
            created.filtered('rms_used_alternative_of_id')._rms_apply_part_discounts()
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
                alt._rms_apply_part_discounts()
                if alt.rms_used_lot_id:
                    for move in moves:
                        move._do_unreserve()
                        move.move_line_ids.unlink()
                        self.env['stock.move.line'].create({
                            'move_id': move.id, 'product_id': move.product_id.id,
                            'product_uom_id': move.product_uom.id, 'quantity': move.product_uom_qty,
                            'lot_id': alt.rms_used_lot_id.id, 'location_id': move.location_id.id,
                            'location_dest_id': move.location_dest_id.id, 'company_id': move.company_id.id})
            repair.write({'rms_parts_choice': 'used', 'rms_stage': 'repair'})
        return True

    def action_rms_choose_new(self):
        self.write({'rms_parts_choice': 'new', 'rms_stage': 'repair'})
        return True
