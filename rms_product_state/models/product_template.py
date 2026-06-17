from odoo import models, fields, api

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    product_state_id = fields.Many2one(
        'product.state',
        string='Estado de Producto',
        default=lambda self: self._default_product_state_id(),
        help="Estado del producto en el catálogo"
    )

    @api.model
    def _default_product_state_id(self):
        return self.env['product.state'].search([('code', '=', 'new')], limit=1)

    @api.model
    def _cron_archive_discontinued_products(self):
        discontinued_state = self.env['product.state'].search([('code', '=', 'discontinued')], limit=1)
        if not discontinued_state:
            return
        
        products = self.search([
            ('product_state_id', '=', discontinued_state.id),
            ('active', '=', True)
        ])
        
        for product in products:
            if product.qty_available <= 0:
                product.active = False
                product.message_post(
                    body="Este producto ha sido archivado automáticamente porque su estado es 'Descontinuado' y su stock está liquidado (0 unidades)."
                )

