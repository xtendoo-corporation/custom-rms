from odoo import _, api, fields, models
from odoo.exceptions import UserError


class StockCession(models.Model):
    """Depósitos en clientes sobre las cesiones: varias líneas, salida con
    checklist de pistola y vuelta (total o por partes) también con checklist.
    La cesión clásica de un solo producto («Confirmar y Ceder») sigue igual."""

    _inherit = 'stock.cession'

    # Con líneas de depósito el producto único de la cesión clásica sobra.
    product_id = fields.Many2one(required=False)
    rms_line_ids = fields.One2many('rms.deposit.line', 'cession_id', string='Equipos a dejar en depósito')
    rms_unit_ids = fields.One2many('rms.deposit.unit', 'cession_id', string='Equipos entregados')
    rms_picking_ids = fields.One2many('stock.picking', 'rms_cession_id', string='Albaranes del depósito')
    rms_out_count = fields.Float(string='Unidades en el cliente', compute='_compute_rms_deposit', store=True)
    rms_deposit_state = fields.Selection([
        ('draft', 'Borrador'),
        ('preparing', 'Preparando salida'),
        ('out', 'En el cliente'),
        ('partial', 'Devuelto en parte'),
        ('returned', 'Devuelto todo'),
        ('cancel', 'Cancelado'),
    ], string='Situación del depósito', compute='_compute_rms_deposit', store=True)
    rms_days_out = fields.Integer(string='Días fuera', compute='_compute_rms_days_out')

    @api.depends('state', 'picking_id.state', 'rms_unit_ids.state', 'rms_unit_ids.qty_returned')
    def _compute_rms_deposit(self):
        for cession in self:
            units = cession.rms_unit_ids
            out_units = units.filtered(lambda u: u.state == 'out')
            cession.rms_out_count = sum(u.quantity - u.qty_returned for u in out_units)
            if cession.state == 'cancel':
                state = 'cancel'
            elif units:
                if not out_units:
                    state = 'returned'
                elif any(u.state == 'returned' or u.qty_returned for u in units):
                    state = 'partial'
                else:
                    state = 'out'
            elif cession.picking_id and cession.picking_id.state not in ('done', 'cancel'):
                state = 'preparing'
            elif cession.state == 'done':
                state = 'out'
            else:
                state = 'draft'
            cession.rms_deposit_state = state

    def _compute_rms_days_out(self):
        for cession in self:
            cession.rms_days_out = max(cession.rms_unit_ids.filtered(lambda u: u.state == 'out').mapped('days_out'),
                                       default=0)

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        company = self.env['res.company'].browse(values.get('company_id')) or self.env.company
        if 'location_src_id' in fields_list and not values.get('location_src_id'):
            warehouse = self.env['stock.warehouse'].search([('company_id', '=', company.id)], limit=1)
            values['location_src_id'] = warehouse.lot_stock_id.id
        if 'location_dest_id' in fields_list and not values.get('location_dest_id'):
            values['location_dest_id'] = self._rms_deposit_location(company).id
        return values

    @api.model
    def _rms_deposit_location(self, company):
        """Ubicación «Depósitos en clientes» de la empresa (se crea la primera
        vez). De tránsito: el material sigue siendo nuestro, pero no cuenta como
        disponible para vender."""
        Location = self.env['stock.location'].sudo()
        location = Location.search([
            ('rms_customer_deposit', '=', True), ('company_id', '=', company.id)], limit=1)
        if not location:
            location = Location.create({
                'name': _("Depósitos en clientes"), 'usage': 'transit',
                'company_id': company.id, 'rms_customer_deposit': True,
            })
        return location

    def _rms_warehouse(self):
        self.ensure_one()
        return self.location_src_id.warehouse_id or self.env['stock.warehouse'].search(
            [('company_id', '=', self.company_id.id)], limit=1)

    def _rms_new_picking(self, role, picking_type, source, dest, quantities):
        self.ensure_one()
        if not picking_type:
            raise UserError(_("No hay un tipo de operación de almacén para este depósito."))
        picking = self.env['stock.picking'].with_company(self.company_id).create({
            'company_id': self.company_id.id,
            'partner_id': self.partner_id.id,
            'picking_type_id': picking_type.id,
            'location_id': source.id,
            'location_dest_id': dest.id,
            'origin': self.name,
            'rms_deposit_role': role,
            'rms_cession_id': self.id,
            'move_ids': [(0, 0, {
                'description_picking': _("Depósito %s", self.name),
                'company_id': self.company_id.id,
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
                'location_id': source.id,
                'location_dest_id': dest.id,
            }) for product, qty in quantities if qty > 0],
        })
        picking.action_confirm()
        picking.action_assign()
        return picking

    def action_confirm(self):
        if any(cession.rms_line_ids for cession in self):
            raise UserError(_(
                "Este depósito tiene varios equipos: usa «Preparar salida con pistola» "
                "en lugar de «Confirmar y Ceder»."))
        return super().action_confirm()

    def action_rms_prepare_out(self):
        """Crea el albarán de salida del depósito (sin validar) y abre su checklist."""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_("Este depósito ya no está en borrador."))
        if not self.rms_line_ids:
            raise UserError(_("Añade primero los equipos que se dejan en depósito."))
        if self.picking_id and self.picking_id.state not in ('done', 'cancel'):
            return self.picking_id.action_open_delivery_check()
        quantities = {}
        for line in self.rms_line_ids:
            quantities[line.product_id] = quantities.get(line.product_id, 0.0) + line.quantity
        picking = self._rms_new_picking(
            'out', self._rms_warehouse().out_type_id or self.env['stock.picking.type'].search([
                ('company_id', '=', self.company_id.id), ('code', '=', 'outgoing')], limit=1),
            self.location_src_id, self.location_dest_id, quantities.items())
        self.sudo().write({'picking_id': picking.id})
        return picking.action_open_delivery_check()

    def action_rms_register_return(self):
        """Albarán de vuelta con lo que sigue en casa del cliente; se lee con
        la pistola lo que regresa y el resto sigue fuera."""
        self.ensure_one()
        open_return = self.rms_picking_ids.filtered(
            lambda p: p.rms_deposit_role == 'return' and p.state not in ('done', 'cancel'))[:1]
        if open_return:
            return open_return.action_open_delivery_check()
        quantities = {}
        for unit in self.rms_unit_ids.filtered(lambda u: u.state == 'out'):
            quantities[unit.product_id] = quantities.get(unit.product_id, 0.0) + unit.quantity - unit.qty_returned
        if not quantities:
            raise UserError(_("No queda nada de este depósito en casa del cliente."))
        warehouse = self._rms_warehouse()
        picking = self._rms_new_picking(
            'return', warehouse.in_type_id or self.env['stock.picking.type'].search([
                ('company_id', '=', self.company_id.id), ('code', '=', 'incoming')], limit=1),
            self.location_dest_id, self.location_src_id, quantities.items())
        return picking.action_open_delivery_check()

    def action_rms_view_units(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('rms_stock_delivery_check.action_deposit_unit')
        action['domain'] = [('cession_id', '=', self.id)]
        action['context'] = {}
        return action

    def _rms_picking_done(self, picking):
        """Al validarse un albarán del depósito: apunta lo que ha salido o lo
        que ha vuelto, unidad a unidad."""
        self.ensure_one()
        Unit = self.env['rms.deposit.unit']
        now = fields.Datetime.now()
        lines = picking.move_line_ids.filtered(lambda l: l.quantity > 0)
        if picking.rms_deposit_role == 'out':
            Unit.create([{
                'cession_id': self.id, 'product_id': line.product_id.id, 'lot_id': line.lot_id.id,
                'quantity': line.quantity, 'date_out': now, 'out_picking_id': picking.id,
            } for line in lines])
            if self.state == 'draft':
                self.write({'state': 'done', 'picking_id': picking.id})
            return
        for line in lines:
            pending = line.quantity
            units = self.rms_unit_ids.filtered(
                lambda u: u.state == 'out' and u.product_id == line.product_id
                and (u.lot_id == line.lot_id if line.lot_id else not u.lot_id)).sorted('date_out')
            for unit in units:
                if pending <= 0:
                    break
                taken = min(pending, unit.quantity - unit.qty_returned)
                pending -= taken
                vals = {'qty_returned': unit.qty_returned + taken, 'return_picking_id': picking.id}
                if vals['qty_returned'] >= unit.quantity:
                    vals.update(state='returned', date_return=now)
                unit.write(vals)


class StockLocation(models.Model):
    _inherit = 'stock.location'

    rms_customer_deposit = fields.Boolean(
        string='Depósitos en clientes',
        help="Ubicación donde Odoo lleva el material que está en depósito en casa de un cliente.")


class RmsDepositLine(models.Model):
    _name = 'rms.deposit.line'
    _description = 'Línea de depósito en cliente'

    cession_id = fields.Many2one('stock.cession', string='Depósito', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='cession_id.company_id', store=True)
    product_id = fields.Many2one('product.product', string='Producto', required=True)
    quantity = fields.Float(string='Cantidad', required=True, default=1.0, digits='Product Unit')

    _quantity_positive = models.Constraint('CHECK(quantity > 0)', 'La cantidad debe ser mayor que cero.')


class RmsDepositUnit(models.Model):
    """Un equipo (o una cantidad de accesorios) que ha salido en depósito."""

    _name = 'rms.deposit.unit'
    _description = 'Equipo en depósito en cliente'
    _order = 'date_out, id'
    _rec_name = 'lot_id'

    cession_id = fields.Many2one('stock.cession', string='Depósito', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='cession_id.company_id', store=True, string='Empresa')
    partner_id = fields.Many2one(related='cession_id.partner_id', store=True, string='Cliente', index=True)
    product_id = fields.Many2one('product.product', string='Producto', required=True)
    lot_id = fields.Many2one('stock.lot', string='Nº de serie', index=True)
    product_state_id = fields.Many2one(related='lot_id.product_state_id', string='Estado')
    quantity = fields.Float(string='Cantidad', default=1.0, digits='Product Unit')
    qty_returned = fields.Float(string='Devuelta', digits='Product Unit')
    state = fields.Selection([
        ('out', 'En el cliente'),
        ('returned', 'Devuelto'),
    ], string='Situación', default='out', required=True, index=True)
    date_out = fields.Datetime(string='Salió el', required=True)
    date_return = fields.Datetime(string='Volvió el')
    days_out = fields.Integer(string='Días fuera', compute='_compute_days_out')
    out_picking_id = fields.Many2one('stock.picking', string='Albarán de salida')
    return_picking_id = fields.Many2one('stock.picking', string='Albarán de vuelta')

    @api.depends('date_out', 'date_return', 'state')
    def _compute_days_out(self):
        now = fields.Datetime.now()
        for unit in self:
            end = unit.date_return if unit.state == 'returned' and unit.date_return else now
            unit.days_out = max((end - unit.date_out).days, 0) if unit.date_out else 0
