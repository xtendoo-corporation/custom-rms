from collections import defaultdict

from odoo import fields, models
from odoo.fields import Domain


class RmsCatalogCard(models.Model):
    _name = 'rms.catalog.card'
    _inherit = ['product.catalog.mixin']
    _description = 'Ficha del catálogo B2B (asignación de productos)'
    _order = 'page_key'

    page_key = fields.Char(
        required=True, index=True, copy=False,
        help="Clave de la ficha tal y como aparece en el catálogo estático "
             "(objeto PAGES de static/catalog/index.html).",
    )
    brand = fields.Char(string='Marca')
    title = fields.Char(string='Título')
    line_ids = fields.One2many(
        'rms.catalog.card.line', 'card_id', string='Productos asignados',
    )
    product_count = fields.Integer(compute='_compute_product_count')

    _sql_constraints = [
        ('page_key_uniq', 'unique(page_key)',
         'Ya existe una ficha del catálogo con esta clave (page_key).'),
    ]

    def _compute_product_count(self):
        for card in self:
            card.product_count = len(card.line_ids)

    def _compute_display_name(self):
        for card in self:
            card.display_name = '[%s] %s' % (card.page_key, card.title or card.brand or '')

    def _get_product_catalog_domain(self):
        return super()._get_product_catalog_domain() & Domain('sale_ok', '=', True)

    def _get_product_catalog_record_lines(self, product_ids, **kwargs):
        self.ensure_one()
        grouped_lines = defaultdict(lambda: self.env['rms.catalog.card.line'])
        for line in self.line_ids:
            if line.product_id.id in product_ids:
                grouped_lines[line.product_id] |= line
        return grouped_lines

    def _get_product_catalog_order_data(self, products, **kwargs):
        res = super()._get_product_catalog_order_data(products, **kwargs)
        for product in products:
            res[product.id]['price'] = product.list_price
        return res

    def _update_order_line_info(self, product_id, quantity, **kwargs):
        self.ensure_one()
        line = self.line_ids.filtered(lambda l: l.product_id.id == product_id)
        if quantity > 0:
            if not line:
                self.env['rms.catalog.card.line'].create({
                    'card_id': self.id,
                    'product_id': product_id,
                })
        elif line:
            line.unlink()
        return self.env['product.product'].browse(product_id).list_price


class RmsCatalogCardLine(models.Model):
    _name = 'rms.catalog.card.line'
    _description = 'Producto asignado a una ficha del catálogo B2B'

    card_id = fields.Many2one(
        'rms.catalog.card', required=True, ondelete='cascade', index=True,
    )
    product_id = fields.Many2one(
        'product.product', required=True, ondelete='cascade', string='Producto',
    )

    _sql_constraints = [
        ('card_product_uniq', 'unique(card_id, product_id)',
         'Este producto ya está asignado a esta ficha.'),
    ]

    def _get_product_catalog_lines_data(self, **kwargs):
        if not self:
            return {'quantity': 0, 'price': 0, 'readOnly': False}
        self.ensure_one()
        return {
            'quantity': 1,
            'price': self.product_id.list_price,
            'readOnly': False,
        }
