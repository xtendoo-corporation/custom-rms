from odoo import api, fields, models, _
from odoo.exceptions import UserError
class StockCession(models.Model):
    _name = 'stock.cession'
    _description = 'Cesion de Mercancia a Cliente / Externa'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'
    name = fields.Char(
        string='Referencia',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('Nuevo'),
    )
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('done', 'Cedido'),
        ('cancel', 'Cancelado'),
    ], string='Estado', default='draft', tracking=True)
    date = fields.Datetime(string='Fecha', default=fields.Datetime.now, required=True)
    partner_id = fields.Many2one('res.partner', string='Cliente Destino', required=True)
    location_src_id = fields.Many2one(
        'stock.location',
        string='Ubicacion Origen (Inventario)',
        required=True,
        domain="[('usage', '=', 'internal')]"
    )
    location_dest_id = fields.Many2one(
        'stock.location',
        string='Ubicacion Destino (Cliente/Externa)',
        required=True
    )
    product_id = fields.Many2one('product.product', string='Producto', required=True, domain="[('type', 'in', ['product', 'consu'])]")
    quantity = fields.Float(string='Cantidad', required=True, default=1.0)
    uom_id = fields.Many2one('uom.uom', string='UdM', related='product_id.uom_id')
    picking_id = fields.Many2one('stock.picking', string='Movimiento Generado', readonly=True, copy=False)
    notes = fields.Text(string='Notas')
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('Nuevo')) == _('Nuevo'):
                vals['name'] = self.env['ir.sequence'].next_by_code('stock.cession') or _('Nuevo')
        return super().create(vals_list)
    def action_confirm(self):
        for record in self:
            if record.state != 'draft':
                continue
            if record.quantity <= 0:
                raise UserError(_('La cantidad a ceder debe ser mayor que cero.'))
            # Generar el movimiento de stock (albaran de salida o interno)
            picking_type = self.env['stock.picking.type'].search([
                ('default_location_src_id', '=', record.location_src_id.id),
                ('code', 'in', ['outgoing', 'internal'])
            ], limit=1)
            if not picking_type:
                # Buscar cualquier picking type interno de la compania
                picking_type = self.env['stock.picking.type'].search([
                    ('company_id', '=', self.env.company.id),
                    ('code', '=', 'internal')
                ], limit=1)
                if not picking_type:
                    raise UserError(_("No se ha encontrado un tipo de operacion valido para mover esta mercancia."))
            picking_vals = {
                'partner_id': record.partner_id.id,
                'location_id': record.location_src_id.id,
                'location_dest_id': record.location_dest_id.id,
                'picking_type_id': picking_type.id,
                'origin': record.name,
                'move_ids': [(0, 0, {
                    'name': _('Cesion ') + record.name,
                    'product_id': record.product_id.id,
                    'product_uom_qty': record.quantity,
                    'product_uom': record.uom_id.id,
                    'location_id': record.location_src_id.id,
                    'location_dest_id': record.location_dest_id.id,
                })]
            }
            picking = self.env['stock.picking'].create(picking_vals)
            picking.action_confirm()
            # Forzar la valdiacion automatica
            picking.action_assign()
            for move in picking.move_ids:
                move.quantity = move.product_uom_qty
            picking.button_validate()
            record.write({
                'picking_id': picking.id,
                'state': 'done'
            })
    def action_cancel(self):
        for record in self:
            if record.picking_id and record.picking_id.state != 'cancel':
                raise UserError(_('No se puede cancelar una cesión que ya tiene un movimiento de stock validado. Cancela/devuelve el movimiento primero.'))
            record.state = 'cancel'
    def action_draft(self):
        for record in self:
            record.state = 'draft'
