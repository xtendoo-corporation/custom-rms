import logging

from odoo import models, fields, api

_logger = logging.getLogger(__name__)


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

        # Avanzar por ID evita repetir productos con stock o con errores.
        last_id = 0
        while True:
            products = self.search([
                ('product_state_id', '=', discontinued_state.id),
                ('active', '=', True),
                ('id', '>', last_id),
            ], order='id', limit=100)
            if not products:
                break
            last_id = products[-1].id
            for product in products:
                try:
                    with self.env.cr.savepoint():
                        if product.qty_available <= 0:
                            product.active = False
                            product.message_post(
                                body="Este producto ha sido archivado automáticamente porque su estado es 'Descontinuado' y su stock está liquidado (0 unidades)."
                            )
                except Exception:
                    # El fallo de un producto no debe abortar el resto del lote.
                    _logger.exception('No se pudo archivar el producto %s', product.id)
