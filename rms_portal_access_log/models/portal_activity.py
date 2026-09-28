import logging
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Segundos durante los que un mismo evento repetido (recargar la página,
# volver atrás y adelante...) no se vuelve a registrar.
DEDUPE_SECONDS = 30
# Tipos en los que cada repetición cuenta (añadir dos veces = dos unidades).
NO_DEDUPE_TYPES = ('quote_add',)
DEDUPE_FIELDS = ('page_key', 'product_tmpl_id', 'sale_order_id', 'invoice_id', 'project_id', 'name')


class PortalActivity(models.Model):
    _name = 'rms.portal.activity'
    _description = 'Actividad en el Portal de Clientes'
    _order = 'date desc, id desc'

    date = fields.Datetime(string='Fecha', required=True, index=True, readonly=True, default=fields.Datetime.now)
    user_id = fields.Many2one('res.users', string='Usuario', index=True, readonly=True)
    partner_id = fields.Many2one('res.partner', string='Contacto', index=True, readonly=True)
    commercial_partner_id = fields.Many2one(
        'res.partner', string='Empresa', related='partner_id.commercial_partner_id',
        store=True, index=True, readonly=True,
    )
    access_log_id = fields.Many2one(
        'rms.portal.access.log', string='Acceso', index=True, readonly=True, ondelete='set null',
        help='Último inicio de sesión del usuario en el momento de la actividad.',
    )
    activity_type = fields.Selection(
        [
            ('portal_page', 'Pantalla del portal'),
            ('catalog_home', 'Catálogo'),
            ('brand', 'Marca del catálogo'),
            ('card', 'Ficha de producto'),
            ('prices', 'Consulta de precios'),
            ('search', 'Búsqueda en el catálogo'),
            ('quote_add', 'Añadido al presupuesto'),
            ('quote_pdf', 'Descarga del presupuesto'),
            ('sale_order', 'Presupuesto / pedido'),
            ('invoice', 'Factura'),
            ('project', 'Proyecto de instalación'),
        ],
        string='Tipo', required=True, index=True, readonly=True,
    )
    name = fields.Char(string='Detalle', readonly=True)
    brand = fields.Char(string='Marca', readonly=True)
    page_key = fields.Char(string='Clave de ficha', index=True, readonly=True)
    page_title = fields.Char(string='Ficha', readonly=True)
    card_id = fields.Many2one('rms.catalog.card', string='Ficha del catálogo', readonly=True, ondelete='set null')
    product_tmpl_id = fields.Many2one('product.template', string='Producto', index=True, readonly=True, ondelete='set null')
    sale_order_id = fields.Many2one('sale.order', string='Presupuesto / pedido', readonly=True, ondelete='set null')
    invoice_id = fields.Many2one('account.move', string='Factura', readonly=True, ondelete='set null')
    project_id = fields.Many2one('rms.installation.project', string='Proyecto', readonly=True, ondelete='set null')
    result_count = fields.Integer(string='Resultados', readonly=True, help='Resultados de la búsqueda (solo búsquedas).')
    url = fields.Char(string='URL', readonly=True)

    @api.model
    def _log(self, activity_type, **vals):
        """Registra una actividad del usuario actual si es de portal.

        Nunca debe romper la pantalla que la llama: cualquier error se
        registra en el log y se ignora.
        """
        user = self.env.user
        if not user.share or user._is_public():
            return self.browse()
        try:
            with self.env.cr.savepoint():
                return self._log_unsafe(user, activity_type, vals)
        except Exception:
            _logger.exception('No se pudo registrar la actividad de portal %s', activity_type)
            return self.browse()

    def _log_unsafe(self, user, activity_type, vals):
        Activity = self.sudo()
        now = fields.Datetime.now()
        if activity_type not in NO_DEDUPE_TYPES:
            domain = [
                ('user_id', '=', user.id),
                ('activity_type', '=', activity_type),
                ('date', '>=', now - timedelta(seconds=DEDUPE_SECONDS)),
            ]
            domain += [(field, '=', vals.get(field) or False) for field in DEDUPE_FIELDS]
            if Activity.search_count(domain, limit=1):
                return self.browse()

        if vals.get('page_key') and not vals.get('card_id'):
            card = self.env['rms.catalog.card'].sudo().search([('page_key', '=', vals['page_key'])], limit=1)
            vals['card_id'] = card.id or False
        access_log = self.env['rms.portal.access.log'].sudo().search([('user_id', '=', user.id)], limit=1)
        return Activity.create({
            **vals,
            'activity_type': activity_type,
            'date': now,
            'user_id': user.id,
            'partner_id': user.partner_id.id,
            'access_log_id': access_log.id or False,
        })
