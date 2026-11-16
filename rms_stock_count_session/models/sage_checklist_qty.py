# -*- coding: utf-8 -*-
"""Cotejo con Sage de lo que NO lleva nº de serie (cables, fundas, hierros,
accesorios). Vista SQL de solo lectura, siempre al día, como rms.sage.checklist.

Una fila por NAVE física + producto: cantidad en Sage (las 3 empresas
sumadas, con su desglose), cantidad contada con el botón "Por cantidad" del
escáner (o leyendo el código de barras del producto) y la diferencia.
"""
from odoo import fields, models, tools

QTY_STATES = [('ok', 'Cuadra'), ('missing', 'Falta'), ('extra', 'Sobra'),
              ('pending', 'Sin contar'), ('not_in_sage', 'No está en Sage')]


class SageChecklistQty(models.Model):
    _name = 'rms.sage.checklist.qty'
    _description = 'Checklist de Sage por cantidad (sin nº de serie)'
    _auto = False
    _order = 'site_number, brand_categ_id, default_code, id'
    _rec_name = 'default_code'

    site_number = fields.Integer(string='Nº de nave', readonly=True, aggregator=False)
    site_name = fields.Char(string='Nave', readonly=True)
    brand_categ_id = fields.Many2one('product.category', string='Marca', readonly=True)
    product_id = fields.Many2one('product.product', string='Producto', readonly=True)
    default_code = fields.Char(string='Referencia', readonly=True)
    article_code = fields.Char(string='Artículo Sage', readonly=True)
    article_name = fields.Char(string='Nombre en Sage', readonly=True)
    product_missing = fields.Boolean(string='Falta crear el producto', readonly=True)
    serial_tracked = fields.Boolean(string='En Odoo lleva nº de serie', readonly=True)
    sage_qty = fields.Float(string='Sage', readonly=True, digits=(16, 3))
    sage_qty_01 = fields.Float(string='Sage RMS', readonly=True, digits=(16, 3))
    sage_qty_02 = fields.Float(string='Sage Espacio', readonly=True, digits=(16, 3))
    sage_qty_03 = fields.Float(string='Sage RJB', readonly=True, digits=(16, 3))
    company_breakdown = fields.Char(string='Por empresa', readonly=True)
    counted_qty = fields.Float(string='Contado', readonly=True, digits=(16, 3))
    difference = fields.Float(string='Diferencia', readonly=True, digits=(16, 3))
    state = fields.Selection(QTY_STATES, string='Resultado', readonly=True)
    scan_count = fields.Integer(string='Nº de apuntes', readonly=True, aggregator=False)
    session_count = fields.Integer(string='Nº de recuentos', readonly=True, aggregator=False)
    last_scanned_at = fields.Datetime(string='Último apunte', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        # El marcador del escáner y esta vista buscan las lecturas por cantidad.
        self.env.cr.execute("CREATE INDEX IF NOT EXISTS rms_count_scan_qty_product_idx "
                            "ON rms_stock_count_scan(product_id) WHERE scan_type = 'product'")
        # Cada lado (Sage / contado) se agrega por separado ANTES de unir: ni
        # varias lecturas ni varias empresas doblan cantidades.
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW rms_sage_checklist_qty AS (
            WITH sage_company AS (
                -- Sage: por nave, producto (o artículo si no tiene producto) y empresa.
                SELECT COALESCE(w.site_number, 0) AS site, l.product_id,
                       CASE WHEN l.product_id IS NULL THEN l.article_code END AS article_key,
                       l.sage_company_code, sum(l.quantity) AS qty,
                       min(l.id) AS line_id, min(l.article_code) AS article_code,
                       min(l.article_name) AS article_name, min(l.brand_categ_id) AS brand_categ_id
                  FROM rms_sage_stock_line l
                  LEFT JOIN rms_sage_warehouse w ON w.id = l.sage_warehouse_id
                 WHERE l.is_current AND l.stock_kind = 'stock' AND l.quantity > 0
                   AND COALESCE(l.serial_normalized, '') IN ('', 'SN')
                   AND NOT COALESCE(l.in_deposit, FALSE)
                 GROUP BY 1, 2, 3, 4
            ), sage AS (
                SELECT site, product_id, article_key, sum(qty) AS qty,
                       COALESCE(sum(qty) FILTER (WHERE sage_company_code = '01'), 0) AS qty_01,
                       COALESCE(sum(qty) FILTER (WHERE sage_company_code = '02'), 0) AS qty_02,
                       COALESCE(sum(qty) FILTER (WHERE sage_company_code = '03'), 0) AS qty_03,
                       string_agg(
                           CASE sage_company_code WHEN '01' THEN 'RMS' WHEN '02' THEN 'Espacio'
                                WHEN '03' THEN 'RJB' ELSE COALESCE(sage_company_code, '?') END
                           || ' ' || trim(trailing '.' from trim(trailing '0' from round(qty::numeric, 3)::text)),
                           ' · ' ORDER BY sage_company_code) AS breakdown,
                       min(line_id) AS line_id, min(article_code) AS article_code,
                       min(article_name) AS article_name, min(brand_categ_id) AS brand_categ_id
                  FROM sage_company
                 GROUP BY 1, 2, 3
            ), counted AS (
                -- Lecturas por cantidad válidas, por nave de su ubicación y producto.
                -- Nave = nº final del código del almacén de Odoo (RMS7/ET7/RJB7 -> 7).
                SELECT COALESCE(substring(btrim(wh.code) from '[0-9]+$')::int, 0) AS site,
                       sc.product_id, sum(sc.quantity) AS qty, count(*) AS scan_count,
                       count(DISTINCT sc.session_id) AS session_count, max(sc.scanned_at) AS last_scanned_at
                  FROM rms_stock_count_scan sc
                  JOIN rms_stock_count_session ss ON ss.id = sc.session_id
                  LEFT JOIN stock_location loc ON loc.id = COALESCE(sc.location_id, ss.location_id)
                  LEFT JOIN stock_warehouse wh ON wh.id = loc.warehouse_id
                 WHERE sc.scan_type = 'product' AND sc.product_id IS NOT NULL
                   AND ss.state <> 'cancel' AND NOT COALESCE(sc.ignored, FALSE)
                 GROUP BY 1, 2
            )
            SELECT COALESCE(s.line_id::bigint,
                            1000000000000 + c.product_id::bigint * 1000 + c.site) AS id,
                   COALESCE(s.site, c.site) AS site_number,
                   CASE COALESCE(s.site, c.site)
                        WHEN 0 THEN NULL WHEN 1 THEN 'Madrid' WHEN 2 THEN 'Nave 22' WHEN 3 THEN 'Alfaomega'
                        WHEN 4 THEN 'Cataluña (Alex)' WHEN 5 THEN 'Cataluña (Vicente)' WHEN 6 THEN 'Mallorca'
                        WHEN 7 THEN 'Sevilla' ELSE 'Nave ' || COALESCE(s.site, c.site) END AS site_name,
                   COALESCE(s.brand_categ_id, pt.categ_id) AS brand_categ_id,
                   COALESCE(s.product_id, c.product_id) AS product_id,
                   COALESCE(pp.default_code, s.article_code) AS default_code,
                   s.article_code, s.article_name,
                   (s.line_id IS NOT NULL AND s.product_id IS NULL) AS product_missing,
                   COALESCE(pt.tracking, 'none') <> 'none' AS serial_tracked,
                   COALESCE(s.qty, 0) AS sage_qty,
                   COALESCE(s.qty_01, 0) AS sage_qty_01, COALESCE(s.qty_02, 0) AS sage_qty_02,
                   COALESCE(s.qty_03, 0) AS sage_qty_03,
                   s.breakdown AS company_breakdown,
                   COALESCE(c.qty, 0) AS counted_qty,
                   COALESCE(c.qty, 0) - COALESCE(s.qty, 0) AS difference,
                   CASE WHEN c.product_id IS NULL THEN 'pending'
                        WHEN s.line_id IS NULL THEN 'not_in_sage'
                        WHEN round((c.qty - s.qty)::numeric, 3) = 0 THEN 'ok'
                        WHEN c.qty < s.qty THEN 'missing'
                        ELSE 'extra' END AS state,
                   COALESCE(c.scan_count, 0) AS scan_count,
                   COALESCE(c.session_count, 0) AS session_count,
                   c.last_scanned_at
              FROM sage s
              FULL OUTER JOIN counted c ON c.site = s.site AND c.product_id = s.product_id
              LEFT JOIN product_product pp ON pp.id = COALESCE(s.product_id, c.product_id)
              LEFT JOIN product_template pt ON pt.id = pp.product_tmpl_id
            )""")
