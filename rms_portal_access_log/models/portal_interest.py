from odoo import fields, models, tools


class PortalInterest(models.Model):
    """Resumen de interés de cada contacto por cada ficha del catálogo.

    Agrupa la actividad (fichas abiertas, precios consultados, productos
    añadidos al presupuesto) para ver de un vistazo qué productos mira más
    cada cliente.
    """
    _name = 'rms.portal.interest'
    _description = 'Interés de clientes por fichas del catálogo'
    _auto = False
    _order = 'score desc, last_date desc'
    _rec_name = 'page_title'

    partner_id = fields.Many2one('res.partner', string='Contacto', readonly=True)
    commercial_partner_id = fields.Many2one('res.partner', string='Empresa', readonly=True)
    page_key = fields.Char(string='Clave de ficha', readonly=True)
    page_title = fields.Char(string='Ficha', readonly=True)
    brand = fields.Char(string='Marca', readonly=True)
    card_id = fields.Many2one('rms.catalog.card', string='Ficha del catálogo', readonly=True)
    view_count = fields.Integer(string='Visitas a la ficha', readonly=True)
    price_count = fields.Integer(string='Consultas de precio', readonly=True)
    quote_count = fields.Integer(string='Añadidos al presupuesto', readonly=True)
    score = fields.Integer(
        string='Puntuación', readonly=True,
        help='Visitas + 2 × consultas de precio + 3 × añadidos al presupuesto.',
    )
    first_date = fields.Datetime(string='Primera vez', readonly=True)
    last_date = fields.Datetime(string='Última vez', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    MIN(a.id) AS id,
                    a.partner_id,
                    MAX(a.commercial_partner_id) AS commercial_partner_id,
                    a.page_key,
                    COALESCE(MAX(a.page_title), a.page_key) AS page_title,
                    MAX(a.brand) AS brand,
                    MAX(a.card_id) AS card_id,
                    COUNT(*) FILTER (WHERE a.activity_type = 'card') AS view_count,
                    COUNT(*) FILTER (WHERE a.activity_type = 'prices') AS price_count,
                    COUNT(*) FILTER (WHERE a.activity_type = 'quote_add') AS quote_count,
                    COUNT(*) FILTER (WHERE a.activity_type = 'card')
                        + 2 * COUNT(*) FILTER (WHERE a.activity_type = 'prices')
                        + 3 * COUNT(*) FILTER (WHERE a.activity_type = 'quote_add') AS score,
                    MIN(a.date) AS first_date,
                    MAX(a.date) AS last_date
                FROM rms_portal_activity a
                WHERE a.page_key IS NOT NULL
                  AND a.partner_id IS NOT NULL
                  AND a.activity_type IN ('card', 'prices', 'quote_add')
                GROUP BY a.partner_id, a.page_key
            )
        """ % self._table)

    def action_open_activity(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': '%s · %s' % (self.partner_id.display_name, self.page_title),
            'res_model': 'rms.portal.activity',
            'view_mode': 'list',
            'domain': [('partner_id', '=', self.partner_id.id), ('page_key', '=', self.page_key)],
        }
