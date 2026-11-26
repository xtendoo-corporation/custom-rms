# -*- coding: utf-8 -*-
"""Vista "Lista" del escáner: todo lo que Sage dice que hay en la nave que se
cuenta (las 3 empresas juntas, igual que el marcador), por marca > producto >
nº de serie, y qué se ha leído ya en CUALQUIER recuento no cancelado.

Carga perezosa: marcas con sus totales; productos de una marca; nº de serie
de un producto (paginados). Todo con SQL agregado, como scanner_progress.
Nunca devuelve costes ni cantidades de Sage (recuento a ciegas)."""

import re

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import SQL

from .sage_expected import sql_same_serial, sql_scan_reads_line
from .scan_rule import normalize_code
from .stock_count_scan import SAGE_STATE_LABEL, label_print_action

# Las mismas líneas que cuenta el marcador (scanner_progress).
_LIST_SAGE_WHERE = (
    "l.is_current AND l.stock_kind = 'stock' AND l.quantity > 0 "
    "AND COALESCE(l.serial_normalized, '') <> '' AND NOT COALESCE(l.in_deposit, FALSE)"
)
# La misma lectura válida que el marcador y el checklist global.
_LIST_SCAN_MATCH = (
    sql_scan_reads_line('sc', 'l')
    + " AND sc.scan_type = 'serial' AND ss.state <> 'cancel' AND NOT COALESCE(sc.ignored, FALSE)"
      " AND (l.product_id IS NULL OR sc.product_id = l.product_id)"
)
_LIST_FILTERS = ('all', 'pending', 'done')
_SAGE_COMPANY = {'01': 'RMS', '02': 'Espacio', '03': 'RJB'}
_SAGE_STATE = {'nuevo': 'Nuevo', 'demo': 'Demo', '2mano': '2ª Mano'}
_NOT_ALNUM = re.compile(r'[^0-9A-Z]')


class RmsStockCountOperator(models.Model):
    _inherit = "rms.stock.count.operator"

    _LIST_PAGE = 200
    _LIST_PRINT_MAX = 20000

    # ------------------------------------------------------------------
    # Piezas SQL
    # ------------------------------------------------------------------

    def _list_scope(self):
        """Almacenes Sage de la nave (las 3 empresas). Mismos permisos que el
        marcador: basta con poder leer el recuento."""
        self.ensure_one()
        self.session_id.check_access("read")
        self.env["rms.sage.stock.line"].sudo().flush_model()
        self.env["rms.stock.count.session"].flush_model(["state"])
        self.env["rms.stock.count.scan"].flush_model()
        self.env["product.product"].flush_model()
        self.env["product.template"].flush_model()
        return self._progress_warehouses()

    @api.model
    def _list_filter(self, flt):
        return flt if flt in _LIST_FILTERS else 'all'

    @api.model
    def _list_words(self, query):
        words = []
        for word in (query or "").split()[:6]:
            key = _NOT_ALNUM.sub("", normalize_code(word))
            if key:
                words.append(key)
        return words

    @api.model
    def _list_query_sql(self, query, serial_column="l.serial_normalized"):
        """Condición SQL: la línea casa con todas las palabras buscadas (marca,
        referencia, nombre o parte del nº de serie)."""
        conditions = []
        for key in self._list_words(query):
            conditions.append(SQL(
                "(" + serial_column + " LIKE %s OR regexp_replace(upper(concat_ws(' ', l.article_code, l.article_name, "
                "l.model_code, pp.default_code, pt.name->>'es_ES', pt.name->>'en_US', pc.name)), "
                "'[^0-9A-Z]', '', 'g') LIKE %s)",
                "%" + (key.lstrip("0") or key) + "%", "%" + key + "%"))
        return SQL(" AND ").join(conditions) if conditions else SQL("TRUE")

    def _list_base(self, warehouses, flt='all', query='', brand_id=None, key=None):
        """Una fila por equipo con nº de serie de Sage en la nave, con su
        última lectura válida (de cualquier recuento) y si se enseña con el
        filtro y la búsqueda actuales (`shown`)."""
        where = [SQL(_LIST_SAGE_WHERE), SQL("l.sage_warehouse_id = ANY(%s)", warehouses.ids)]
        if brand_id is not None:
            where.append(SQL("COALESCE(l.brand_categ_id, 0) = %s", int(brand_id or 0)))
        if key:
            if key.startswith("p") and key[1:].isdigit():
                where.append(SQL("l.product_id = %s", int(key[1:])))
            elif key.startswith("a:"):
                where.append(SQL("l.product_id IS NULL AND l.article_code = %s", key[2:]))
            else:
                where.append(SQL("FALSE"))
        shown = self._list_query_sql(query)
        if flt == 'pending':
            shown = SQL("(%s) AND s.id IS NULL", shown)
        elif flt == 'done':
            shown = SQL("(%s) AND s.id IS NOT NULL", shown)
        return SQL("""
            SELECT l.id, COALESCE(l.brand_categ_id, 0) AS brand, l.product_id, l.article_code, l.article_name,
                   l.serial, l.serial_normalized, l.state, l.sage_company_code,
                   COALESCE(w.code, l.warehouse_code) AS wh, pp.default_code,
                   COALESCE(pt.name->>'es_ES', pt.name->>'en_US') AS product_name,
                   s.id AS scan_id, s.operator_id, s.session_id, s.scanned_at, ps.code AS read_code,
                   CASE WHEN s.id IS NULL THEN 'todo'
                        WHEN ps.code IN ('new', 'demo', 'second_hand', 'ex_demo') AND NOT (
                                (ps.code = 'new' AND l.state = 'nuevo')
                             OR (ps.code = 'demo' AND l.state = 'demo')
                             OR (ps.code = 'second_hand' AND l.state = '2mano')) THEN 'est'
                        ELSE 'ok' END AS k,
                   (%s) AS shown,
                   CASE WHEN s.sage_match_state = 'confirmed' AND s.sage_match_key = l.serial_normalized
                        THEN s.lot_name END AS read_as,
                   g.id AS sug_id, g.lot_name AS sug_serial
              FROM rms_sage_stock_line l
              LEFT JOIN rms_sage_warehouse w ON w.id = l.sage_warehouse_id
              LEFT JOIN product_product pp ON pp.id = l.product_id
              LEFT JOIN product_template pt ON pt.id = pp.product_tmpl_id
              LEFT JOIN product_category pc ON pc.id = l.brand_categ_id
              LEFT JOIN LATERAL (
                    SELECT sc.id, sc.product_state_id, sc.operator_id, sc.session_id, sc.scanned_at,
                           sc.lot_name, sc.sage_match_state, sc.sage_match_key
                      FROM rms_stock_count_scan sc
                      JOIN rms_stock_count_session ss ON ss.id = sc.session_id
                     WHERE """ + _LIST_SCAN_MATCH + """
                     ORDER BY sc.scanned_at DESC, sc.id DESC LIMIT 1
              ) s ON TRUE
              LEFT JOIN product_state ps ON ps.id = s.product_state_id
              -- Coincidencia probable de ESTE recuento aún sin confirmar (una sola candidata).
              LEFT JOIN LATERAL (
                    SELECT sc.id, COALESCE(sc.lot_name, sc.code) AS lot_name
                      FROM rms_stock_count_scan sc
                     WHERE sc.sage_match_state = 'suggested' AND sc.sage_match_key = l.serial_normalized
                       AND sc.session_id = %s AND NOT COALESCE(sc.ignored, FALSE)
                     ORDER BY sc.id DESC LIMIT 1
              ) g ON s.id IS NULL
             WHERE %s""", shown, self.session_id.id, SQL(" AND ").join(where))

    def _list_show_sage_qty(self):
        """Por defecto lo que va por cantidad se cuenta a ciegas (la Lista no
        enseña la cifra de Sage). Con el parámetro activado, la Lista enseña
        «3 de 6» y el artículo sigue en "Solo lo que falta" hasta completarlo:
        para material suelto que se va encontrando de uno en uno."""
        value = self.env["ir.config_parameter"].sudo().get_param("rms_stock_count_session.list_show_sage_qty")
        return str(value or "").strip().lower() in ("1", "true", "yes", "si", "sí")

    def _list_qty_sql(self, warehouses, flt='all', query=''):
        """Una fila por artículo SIN nº de serie de Sage en la nave (los que
        ofrece el botón "Por cantidad") con lo apuntado en la nave. La cantidad
        de Sage (última columna) solo se devuelve al escáner si está activado
        _list_show_sage_qty; si no, recuento a ciegas."""
        sites = sorted(set(warehouses.mapped("site_number")) - {0})
        partial = self._list_show_sage_qty()
        shown = SQL("bool_or(%s)", self._list_query_sql(query, "''"))
        return SQL("""
            WITH counted AS (
                SELECT sc.product_id, sum(sc.quantity) AS qty
                  FROM rms_stock_count_scan sc
                  JOIN rms_stock_count_session ss ON ss.id = sc.session_id
                  LEFT JOIN stock_location loc ON loc.id = COALESCE(sc.location_id, ss.location_id)
                  LEFT JOIN stock_warehouse wh ON wh.id = loc.warehouse_id
                 WHERE sc.scan_type = 'product' AND sc.product_id IS NOT NULL
                   AND ss.state <> 'cancel' AND NOT COALESCE(sc.ignored, FALSE)
                   AND COALESCE(substring(btrim(wh.code) from '[0-9]+$')::int, 0) = ANY(%s)
                 GROUP BY 1
            )
            SELECT g.brand, g.product_id, g.article_code, g.article_name, g.ok,
                   c.product_id IS NOT NULL AS is_counted, COALESCE(c.qty, 0) AS counted,
                   (g.shown AND %s) AS shown, g.sage_qty
              FROM (
                SELECT COALESCE(min(l.brand_categ_id), 0) AS brand, l.product_id,
                       min(l.article_code) AS article_code, min(l.article_name) AS article_name,
                       bool_and(l.product_id IS NOT NULL AND COALESCE(l.match_state, '') = 'ok') AS ok,
                       %s AS shown, sum(l.quantity) AS sage_qty
                  FROM rms_sage_stock_line l
                  LEFT JOIN product_product pp ON pp.id = l.product_id
                  LEFT JOIN product_template pt ON pt.id = pp.product_tmpl_id
                  LEFT JOIN product_category pc ON pc.id = l.brand_categ_id
                 WHERE """ + self._QTY_SAGE_WHERE + """
                   AND l.sage_warehouse_id = ANY(%s)
                   AND COALESCE(pt.tracking, 'none') = 'none'
                 GROUP BY l.product_id, CASE WHEN l.product_id IS NULL THEN l.article_code END
              ) g
              LEFT JOIN counted c ON c.product_id = g.product_id""",
            sites,
            SQL("COALESCE(c.qty, 0) < g.sage_qty") if flt == 'pending' and partial else
            SQL("c.product_id IS NULL") if flt == 'pending' else
            SQL("c.product_id IS NOT NULL") if flt == 'done' else SQL("TRUE"),
            shown, warehouses.ids)

    def _list_extra_sql(self, query=''):
        """Altas: nº de serie leídos en ESTE recuento que no están en Sage (lo
        mismo que el veredicto rojo "none" del escáner), una fila por equipo."""
        conditions = []
        for key in self._list_words(query):
            conditions.append(SQL(
                "(sc.serial_normalized LIKE %s OR regexp_replace(upper(concat_ws(' ', sc.lot_name, pp.default_code, "
                "pt.name->>'es_ES', pt.name->>'en_US', pc.name)), '[^0-9A-Z]', '', 'g') LIKE %s)",
                "%" + (key.lstrip("0") or key) + "%", "%" + key + "%"))
        return SQL("""
            SELECT max(sc.id) AS id, sc.product_id, sc.serial_normalized, max(sc.lot_name) AS serial,
                   min(pp.default_code) AS default_code,
                   min(COALESCE(pt.name->>'es_ES', pt.name->>'en_US')) AS product_name,
                   string_agg(DISTINCT op.name, ', ') AS operators, max(sc.scanned_at) AS scanned_at
              FROM rms_stock_count_scan sc
              JOIN rms_stock_count_operator op ON op.id = sc.operator_id
              LEFT JOIN product_product pp ON pp.id = sc.product_id
              LEFT JOIN product_template pt ON pt.id = pp.product_tmpl_id
              LEFT JOIN product_category pc ON pc.id = pt.categ_id
             WHERE sc.session_id = %s AND sc.scan_type = 'serial' AND NOT COALESCE(sc.ignored, FALSE)
               AND COALESCE(sc.serial_normalized, '') <> '' AND COALESCE(sc.lot_name, '') <> ''
               AND NOT EXISTS (
                    SELECT 1 FROM rms_sage_stock_line l
                     WHERE l.is_current AND l.serial_normalized <> '' AND l.stock_kind = 'stock' AND l.quantity > 0
                       AND (""" + sql_same_serial('l.serial_normalized', 'sc.serial_normalized') + """
                            OR (sc.sage_match_state = 'confirmed' AND l.serial_normalized = sc.sage_match_key)))
               AND %s
             GROUP BY sc.product_id, sc.serial_normalized""",
            self.session_id.id, SQL(" AND ").join(conditions) if conditions else SQL("TRUE"))

    # ------------------------------------------------------------------
    # Datos de cada nivel
    # ------------------------------------------------------------------

    def _list_time(self, value):
        return fields.Datetime.context_timestamp(self, value).strftime("%d/%m %H:%M") if value else ""

    def _list_summary(self, warehouses, flt, query):
        """Nivel 1: marcas con sus totales (N de M) y las altas del recuento."""
        cr = self.env.cr
        cr.execute(SQL("""
            SELECT x.brand, count(*), count(*) FILTER (WHERE x.scan_id IS NOT NULL),
                   count(*) FILTER (WHERE x.k = 'est'), count(*) FILTER (WHERE x.shown)
              FROM (%s) x GROUP BY 1""", self._list_base(warehouses, flt, query)))
        brands = {row[0]: {"id": row[0], "total": row[1], "counted": row[2], "review": row[3], "shown": row[4],
                           "qty_total": 0, "qty_counted": 0, "qty_shown": 0} for row in cr.fetchall()}
        show_qty = self._list_show_sage_qty()
        cr.execute(SQL("""
            SELECT q.brand, count(*), count(*) FILTER (WHERE q.is_counted), count(*) FILTER (WHERE q.shown),
                   COALESCE(sum(q.sage_qty), 0), COALESCE(sum(LEAST(q.counted, q.sage_qty)), 0)
              FROM (%s) q GROUP BY 1""", self._list_qty_sql(warehouses, flt, query)))
        for brand, total, counted, shown, units, units_counted in cr.fetchall():
            entry = brands.setdefault(brand, {"id": brand, "total": 0, "counted": 0, "review": 0, "shown": 0})
            entry.update(qty_total=total, qty_counted=counted, qty_shown=shown)
            if show_qty:
                # Unidades: es lo que se mueve con cada lectura de material suelto.
                entry.update(qty_units=units, qty_units_counted=units_counted)
        names = {categ.id: categ.name for categ in
                 self.env["product.category"].sudo().browse([b for b in brands if b]).exists()}
        for brand in brands.values():
            brand["name"] = names.get(brand["id"]) or "Sin marca"
        cr.execute(SQL("SELECT count(*) FROM (%s) e", self._list_extra_sql(query)))
        extra = cr.fetchone()[0]
        rows = sorted(brands.values(), key=lambda b: b["name"].casefold())
        return {
            "total": sum(b["total"] for b in rows),
            "counted": sum(b["counted"] for b in rows),
            "review": sum(b["review"] for b in rows),
            "qty_total": sum(b["qty_total"] for b in rows),
            "qty_counted": sum(b["qty_counted"] for b in rows),
            # Solo las marcas con algo que enseñar con el filtro y la búsqueda.
            "brands": [b for b in rows if b["shown"] or b["qty_shown"]],
            "extra_count": 0 if flt == 'pending' else extra,
        }

    def _list_qty_rows(self, warehouses, flt, query):
        """Artículos por cantidad de la nave que se enseñan con el filtro y la
        búsqueda, por marca."""
        self.env.cr.execute(SQL("SELECT q.* FROM (%s) q WHERE q.shown ORDER BY q.article_name, q.article_code",
                                self._list_qty_sql(warehouses, flt, query)))
        by_brand = {}
        for row in self.env.cr.fetchall():
            by_brand.setdefault(row[0], []).append(row)
        return by_brand

    def _list_products(self, warehouses, brand_id, flt, query, qty_by_brand=None):
        """Nivel 2: productos de una marca (N de M) y sus artículos por cantidad."""
        cr = self.env.cr
        cr.execute(SQL("""
            SELECT x.product_id, min(x.default_code), min(x.product_name), min(x.article_code), min(x.article_name),
                   count(*), count(*) FILTER (WHERE x.scan_id IS NOT NULL), count(*) FILTER (WHERE x.k = 'est')
              FROM (%s) x
             GROUP BY x.product_id, CASE WHEN x.product_id IS NULL THEN x.article_code END
            HAVING count(*) FILTER (WHERE x.shown) > 0
             ORDER BY 3 NULLS LAST, 5, 2""", self._list_base(warehouses, flt, query, brand_id=brand_id)))
        products = [{
            "key": "p%d" % row[0] if row[0] else "a:%s" % row[3],
            "product_id": row[0] or False,
            "ref": row[1] or row[3] or "",
            "name": row[2] or row[4] or row[3] or "",
            "no_product": not row[0],
            "total": row[5], "counted": row[6], "review": row[7],
        } for row in cr.fetchall()]
        if qty_by_brand is None:
            qty_by_brand = self._list_qty_rows(warehouses, flt, query)
        qty_rows = qty_by_brand.get(int(brand_id or 0), [])
        by_id = {p.id: p for p in self.env["product.product"].browse([r[1] for r in qty_rows if r[1]]).exists()}
        qty = []
        show_qty = self._list_show_sage_qty()
        for _brand, product_id, article, name, ok, is_counted, counted, _shown, sage_qty in qty_rows:
            product = by_id.get(product_id)
            if product_id and not product:
                continue
            # Misma forma que scanner_qty_search: se abre tal cual en "Por cantidad".
            qty.append({
                "key": "p%d" % product.id if product else "a:%s" % article,
                "product_id": product.id if product else False,
                "name": product.display_name if product else (name or article or ""),
                "ref": (product.default_code if product else "") or article or "",
                "sage_name": name or "", "article": article or "",
                "in_sage": True, "ok": bool(ok and product),
                "is_counted": bool(is_counted), "counted": counted or 0.0,
            })
            if show_qty:
                qty[-1]["sage_qty"] = sage_qty or 0.0
        return {"products": products, "qty": qty}

    def _list_serials(self, warehouses, brand_id, key, flt, query, offset=0, limit=None):
        """Nivel 3: los equipos de un producto, con su color."""
        limit = max(1, min(int(limit or self._LIST_PAGE), 1000))
        offset = max(0, int(offset or 0))
        self.env.cr.execute(SQL("""
            SELECT x.id, x.serial, x.serial_normalized, x.state, x.sage_company_code, x.wh, x.k, x.read_code,
                   x.scanned_at, op.name, ss.name, x.session_id, x.product_id, x.scan_id, count(*) OVER (),
                   x.read_as, x.sug_id, x.sug_serial
              FROM (%s) x
              LEFT JOIN rms_stock_count_operator op ON op.id = x.operator_id
              LEFT JOIN rms_stock_count_session ss ON ss.id = x.session_id
             WHERE x.shown
             ORDER BY x.serial_normalized, x.id
             LIMIT %s OFFSET %s""",
            self._list_base(warehouses, flt, query, brand_id=brand_id, key=key), limit, offset))
        rows = self.env.cr.fetchall()
        return {
            "offset": offset,
            "total": rows[0][14] if rows else 0,
            "rows": [{
                "id": r[0], "serial": r[1] or "", "norm": r[2] or "",
                "st": r[3] or "nuevo", "st_name": _SAGE_STATE.get(r[3], "Nuevo"),
                "co": _SAGE_COMPANY.get(r[4], r[4] or ""), "wh": r[5] or "",
                "k": r[6],
                "read_state": SAGE_STATE_LABEL.get(r[7], "") if r[13] else "",
                "at": self._list_time(r[8]), "by": r[9] or "", "sess": r[10] or "",
                "here": bool(r[11] and r[11] == self.session_id.id),
                "product_id": r[12] or False,
                # Emparejado a mano: la etiqueta lleva otro nº de serie.
                "read_as": r[15] or "",
                # Coincidencia probable sin confirmar: {lectura, nº de serie leído}.
                "sug": {"id": r[16], "serial": r[17] or ""} if r[16] else False,
            } for r in rows],
        }

    # ------------------------------------------------------------------
    # API del escáner (vista "Lista")
    # ------------------------------------------------------------------

    def _list_result(self, warehouses, flt, query):
        progress_names = list(dict.fromkeys(
            "%s (%s)" % (w.name, w.code) if w.name != w.code else w.code
            for w in warehouses.sorted(lambda w: (w.sage_company_code, w.code))))
        result = {
            "has_sage": bool(warehouses),
            "site": " + ".join(progress_names[:3]) + (" + %d más" % (len(progress_names) - 3)
                                                      if len(progress_names) > 3 else ""),
            "filter": flt, "query": query or "",
            "total": 0, "counted": 0, "review": 0, "qty_total": 0, "qty_counted": 0,
            "brands": [], "extra_count": 0, "products": {}, "serials": {},
        }
        if warehouses:
            result.update(self._list_summary(warehouses, flt, query))
        return result

    def scanner_list_brands(self, flt='all', query=''):
        """Marcas de la nave con sus totales. Es lo único que se pide al abrir
        la vista "Lista"."""
        flt = self._list_filter(flt)
        warehouses = self._list_scope()
        return self._list_result(warehouses, flt, query)

    def scanner_list_products(self, brand_id, flt='all', query=''):
        warehouses = self._list_scope()
        if not warehouses:
            return {"products": [], "qty": []}
        return self._list_products(warehouses, brand_id, self._list_filter(flt), query)

    def scanner_list_serials(self, brand_id, key, flt='all', query='', offset=0, limit=None):
        warehouses = self._list_scope()
        if not warehouses:
            return {"offset": 0, "total": 0, "rows": []}
        return self._list_serials(warehouses, brand_id, key, self._list_filter(flt), query, offset, limit)

    def scanner_list_extra(self, query='', offset=0, limit=None):
        """Grupo "No están en Sage": altas de este recuento (filas rojas)."""
        self.ensure_one()
        self.session_id.check_access("read")
        self.env["rms.sage.stock.line"].sudo().flush_model()
        self.env["rms.stock.count.scan"].flush_model()
        self.env["rms.stock.count.operator"].flush_model(["name"])
        limit = max(1, min(int(limit or self._LIST_PAGE), 1000))
        offset = max(0, int(offset or 0))
        self.env.cr.execute(SQL(
            "SELECT e.*, count(*) OVER () FROM (%s) e ORDER BY e.scanned_at DESC, e.id DESC LIMIT %s OFFSET %s",
            self._list_extra_sql(query), limit, offset))
        rows = self.env.cr.fetchall()
        return {
            "offset": offset,
            "total": rows[0][8] if rows else 0,
            "rows": [{
                "id": r[0], "serial": r[3] or "", "norm": r[2] or "", "ref": r[4] or "", "name": r[5] or "",
                "by": r[6] or "", "at": self._list_time(r[7]),
            } for r in rows],
        }

    def scanner_list_refresh(self, flt='all', query='', opened=None, auto=False):
        """Refresco ligero en UNA llamada: totales de las marcas y, solo de
        los grupos abiertos (`opened` = [[marca, [[producto, nº de filas
        cargadas], ...]], ...]), sus productos y sus nº de serie.

        Con `auto` (buscador) el servidor abre los grupos que casan: hasta 8
        marcas y, si son pocos, sus productos con los equipos encontrados."""
        flt = self._list_filter(flt)
        warehouses = self._list_scope()
        result = self._list_result(warehouses, flt, query)
        if not warehouses:
            return result
        visible = {brand["id"] for brand in result["brands"]}
        wanted = []
        if auto and self._list_words(query):
            wanted = [[brand["id"], None] for brand in result["brands"][:8]]
        else:
            for item in (opened or [])[:12]:
                if isinstance(item, (list, tuple)) and len(item) == 2 and item[0] in visible:
                    wanted.append([item[0], item[1] or []])
        open_products = 0
        qty_by_brand = self._list_qty_rows(warehouses, flt, query) if wanted else {}
        for brand_id, product_specs in wanted:
            data = self._list_products(warehouses, brand_id, flt, query, qty_by_brand)
            result["products"][str(brand_id)] = data
            keys = {product["key"] for product in data["products"]}
            if product_specs is None:
                # Buscador: se abren los productos si el resultado es manejable.
                total = sum(len(result["products"][b]["products"]) for b in result["products"])
                product_specs = [[product["key"], self._LIST_PAGE] for product in data["products"]] if total <= 12 else []
            for spec in product_specs:
                if not (isinstance(spec, (list, tuple)) and len(spec) == 2 and spec[0] in keys):
                    continue
                if open_products >= 30:
                    break
                open_products += 1
                loaded = max(self._LIST_PAGE, min(int(spec[1] or 0), 1000))
                result["serials"]["%s|%s" % (brand_id, spec[0])] = self._list_serials(
                    warehouses, brand_id, spec[0], flt, query, 0, loaded)
        return result

    def scanner_list_print(self, brand_id=False, only_pending=True):
        """Botón "Imprimir lista": PDF tipo packing list de la marca abierta o
        de toda la nave, con solo lo que falta o con todo."""
        self.ensure_one()
        self.session_id.check_access("read")
        url = "/report/pdf/rms_stock_count_session.report_count_list/%d?brand_id=%d&only_pending=%d" % (
            self.id, int(brand_id or 0), 1 if only_pending else 0)
        return label_print_action(url)

    def _list_print_data(self, brand_id=False, only_pending=True):
        """Datos del PDF: marca > producto > nº de serie, y al final de cada
        marca lo que va por cantidad (sin la cantidad de Sage)."""
        flt = 'pending' if only_pending else 'all'
        warehouses = self._list_scope()
        result = self._list_result(warehouses, flt, "")
        groups = []
        if not warehouses:
            return {"site": "", "groups": groups, "total": 0, "counted": 0, "truncated": False}
        brand_filter = int(brand_id) if brand_id else None
        self.env.cr.execute(SQL("""
            SELECT x.brand, x.product_id, x.article_code, COALESCE(x.default_code, x.article_code),
                   COALESCE(x.product_name, x.article_name, x.article_code), x.serial, x.state,
                   x.sage_company_code, x.k
              FROM (%s) x
             WHERE x.shown
             ORDER BY x.brand, 5, 4, x.serial_normalized, x.id
             LIMIT %s""", self._list_base(warehouses, flt, "", brand_id=brand_filter), self._LIST_PRINT_MAX + 1))
        rows = self.env.cr.fetchall()
        truncated = len(rows) > self._LIST_PRINT_MAX
        by_brand = {}
        for brand, product_id, article, ref, name, serial, state, company, kind in rows[:self._LIST_PRINT_MAX]:
            group = by_brand.setdefault(brand, {"products": {}, "qty": []})
            product = group["products"].setdefault((product_id, None if product_id else article),
                                                   {"ref": ref or "", "name": name or "", "rows": []})
            product["rows"].append({"serial": serial or "", "state": _SAGE_STATE.get(state, "Nuevo"),
                                    "company": _SAGE_COMPANY.get(company, company or ""), "k": kind})
        qty_rows = [row for brand, brand_rows in self._list_qty_rows(warehouses, flt, "").items()
                    if brand_filter is None or brand == brand_filter for row in brand_rows]
        products = {p.id: p for p in self.env["product.product"].browse([r[1] for r in qty_rows if r[1]]).exists()}
        for brand, product_id, article, name, _ok, is_counted, counted, _shown, _sage_qty in qty_rows:
            product = products.get(product_id)
            by_brand.setdefault(brand, {"products": {}, "qty": []})["qty"].append({
                "ref": (product.default_code if product else "") or article or "",
                "name": (product.name if product else "") or name or article or "",
                "counted": self._qty_text(counted) if is_counted else "",
            })
        names = {brand["id"]: brand["name"] for brand in result["brands"]}
        totals = {brand["id"]: brand for brand in result["brands"]}
        for brand in sorted(by_brand, key=lambda b: (names.get(b) or "").casefold()):
            info = totals.get(brand, {})
            groups.append({
                "name": names.get(brand) or "Sin marca",
                "total": info.get("total", 0), "counted": info.get("counted", 0),
                "products": list(by_brand[brand]["products"].values()), "qty": by_brand[brand]["qty"],
            })
        return {"site": result["site"], "groups": groups, "total": result["total"], "counted": result["counted"],
                "truncated": truncated}


class ReportCountList(models.AbstractModel):
    _name = "report.rms_stock_count_session.report_count_list"
    _description = "Lista de la nave para el recuento (packing list)"

    @api.model
    def _get_report_values(self, docids, data=None):
        data = data or {}
        operator = self.env["rms.stock.count.operator"].browse(docids).exists()[:1]
        if not operator:
            raise UserError("El operario ya no existe en este recuento.")
        operator.check_access("read")

        def flag(name, default):
            value = data.get(name, default)
            return str(value).strip().lower() not in ("0", "false", "", "none")

        brand_id = int(data.get("brand_id") or 0) if str(data.get("brand_id") or "0").isdigit() else 0
        only_pending = flag("only_pending", True)
        values = operator._list_print_data(brand_id, only_pending)
        return {
            "doc_ids": operator.ids, "doc_model": "rms.stock.count.operator", "docs": operator,
            "only_pending": only_pending, "lista": values,
            "printed_at": fields.Datetime.context_timestamp(operator, fields.Datetime.now()).strftime("%d/%m/%Y %H:%M"),
        }
