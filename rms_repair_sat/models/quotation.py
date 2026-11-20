from odoo import api, fields, models
from odoo.exceptions import ValidationError


class RepairFixedPrice(models.Model):
    _name = 'rms.repair.fixed.price'
    _description = 'Tipos de reparación con precio cerrado'

    name = fields.Char(string='Nombre', required=True)
    product_id = fields.Many2one('product.product', string='Servicio', required=True, domain=[('type', '=', 'service')])
    currency_id = fields.Many2one('res.currency', string='Moneda', required=True, default=lambda self: self.env.company.currency_id)
    price = fields.Monetary(string='Precio', required=True)
    active = fields.Boolean(string='Activo', default=True)

    @api.constrains('product_id')
    def _check_service(self):
        for record in self:
            if record.product_id.type != 'service':
                raise ValidationError('El producto debe ser un servicio.')


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def action_confirm(self):
        result = super().action_confirm()
        repairs = self.env['repair.order'].search([('sale_order_id', 'in', self.ids)])
        for repair in repairs:
            repair.write({'rms_accepted_amount': repair.sale_order_id.amount_total,
                          'rms_has_accepted_amount': True, 'rms_reapproved': False})
        return result


class StockLot(models.Model):
    _inherit = 'stock.lot'

    rms_replaces_lot_id = fields.Many2one('stock.lot', string='Sustituye a', copy=False, check_company=True)
