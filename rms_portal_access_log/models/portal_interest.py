from odoo import fields, models, tools

# Modelo de puntuación (lead scoring de comportamiento), 0-100 %.
# Cada señal tiene puntos por acción y un tope, y los topes suman 100: así
# el resultado ya es un porcentaje absoluto, que no depende de otros clientes.
#   · Visita a la ficha ........ 6 pts/visita, tope 25  (interés inicial)
#   · Consulta de precio ....... 15 pts/consulta, tope 25  (señal fuerte, ~3x visita)
#   · Añadido al presupuesto ... 30 pts/vez, tope 40  (la de mayor intención)
#   · Recurrencia .............. 5 pts por cada día distinto que vuelve
#                                (últimos 90 días), tope 10
# Decaimiento exponencial con vida media de 30 días (≈ mitad de un ciclo de
# venta de 1-3 meses): una acción de hace 30 días vale la mitad, de hace
# 90 días un 12,5 %.
HALF_LIFE_DAYS = 30
HOT_THRESHOLD = 70
WARM_THRESHOLD = 40


class PortalInterest(models.Model):
    """Resumen de interés de cada contacto por cada ficha del catálogo.

    Agrupa la actividad (fichas abiertas, precios consultados, productos
    añadidos al presupuesto) para ver de un vistazo qué productos mira más
    cada cliente, con un % de interés que pondera la intención de compra de
    cada acción y lo reciente que es.
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
    return_days = fields.Integer(
        string='Días que ha vuelto', readonly=True,
        help='Días distintos con actividad en esta ficha en los últimos 90 días.',
    )
    score = fields.Integer(
        string='Interés (%)', readonly=True, aggregator='max',
        help='Porcentaje de interés (0-100). Suma, con tope por señal:\n'
             '· Visitas a la ficha: 6 por visita (máx. 25)\n'
             '· Consultas de precio: 15 por consulta (máx. 25)\n'
             '· Añadidos al presupuesto: 30 por vez (máx. 40)\n'
             '· Volver otros días (últimos 90): 5 por día (máx. 10)\n'
             'Cada acción pierde la mitad de su valor cada 30 días.',
    )
    level = fields.Selection(
        [('hot', 'Caliente'), ('warm', 'Templado'), ('cold', 'Frío')],
        string='Nivel', readonly=True,
        help='Caliente: 70 % o más · Templado: 40-69 % · Frío: menos del 40 %.',
    )
    first_date = fields.Datetime(string='Primera vez', readonly=True)
    last_date = fields.Datetime(string='Última vez', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %(table)s AS (
                WITH events AS (
                    SELECT
                        a.*,
                        POWER(0.5, GREATEST(
                            EXTRACT(EPOCH FROM ((NOW() AT TIME ZONE 'UTC') - a.date)), 0
                        ) / 86400.0 / %(half_life)s) AS weight
                    FROM rms_portal_activity a
                    WHERE a.page_key IS NOT NULL
                      AND a.partner_id IS NOT NULL
                      AND a.activity_type IN ('card', 'prices', 'quote_add')
                ),
                grouped AS (
                    SELECT
                        MIN(e.id) AS id,
                        e.partner_id,
                        MAX(e.commercial_partner_id) AS commercial_partner_id,
                        e.page_key,
                        COALESCE(MAX(e.page_title), e.page_key) AS page_title,
                        MAX(e.brand) AS brand,
                        MAX(e.card_id) AS card_id,
                        COUNT(*) FILTER (WHERE e.activity_type = 'card') AS view_count,
                        COUNT(*) FILTER (WHERE e.activity_type = 'prices') AS price_count,
                        COUNT(*) FILTER (WHERE e.activity_type = 'quote_add') AS quote_count,
                        COALESCE(SUM(e.weight) FILTER (WHERE e.activity_type = 'card'), 0) AS w_view,
                        COALESCE(SUM(e.weight) FILTER (WHERE e.activity_type = 'prices'), 0) AS w_price,
                        COALESCE(SUM(e.weight) FILTER (WHERE e.activity_type = 'quote_add'), 0) AS w_quote,
                        COUNT(DISTINCT e.date::date) FILTER (
                            WHERE e.date >= (NOW() AT TIME ZONE 'UTC') - INTERVAL '90 days'
                        ) AS return_days,
                        MIN(e.date) AS first_date,
                        MAX(e.date) AS last_date
                    FROM events e
                    GROUP BY e.partner_id, e.page_key
                ),
                scored AS (
                    SELECT
                        g.*,
                        ROUND(LEAST(100,
                            LEAST(25, 6 * g.w_view)
                            + LEAST(25, 15 * g.w_price)
                            + LEAST(40, 30 * g.w_quote)
                            + LEAST(10, 5 * GREATEST(g.return_days - 1, 0))
                        ))::integer AS score
                    FROM grouped g
                )
                SELECT
                    id, partner_id, commercial_partner_id, page_key, page_title, brand, card_id,
                    view_count, price_count, quote_count, return_days, score,
                    CASE
                        WHEN score >= %(hot)s THEN 'hot'
                        WHEN score >= %(warm)s THEN 'warm'
                        ELSE 'cold'
                    END AS level,
                    first_date, last_date
                FROM scored
            )
        """ % {
            'table': self._table,
            'half_life': HALF_LIFE_DAYS,
            'hot': HOT_THRESHOLD,
            'warm': WARM_THRESHOLD,
        })

    def action_open_activity(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': '%s · %s' % (self.partner_id.display_name, self.page_title),
            'res_model': 'rms.portal.activity',
            'view_mode': 'list',
            'domain': [('partner_id', '=', self.partner_id.id), ('page_key', '=', self.page_key)],
        }
