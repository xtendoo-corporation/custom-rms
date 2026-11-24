# -*- coding: utf-8 -*-
"""Dos ayudas del escáner de recuento:

1. "Coincidencia probable": la etiqueta dice SNDQ703190152400014 y Sage tiene
   SNDQ7031901524040014 (alguien tecleó un 4 de más). La lectura no está en
   Sage, pero se parece a UN nº de serie de Sage aún sin leer: se pregunta al
   operario "¿Es este?" y, si dice que sí, la lectura queda emparejada con esa
   línea de Sage (cuenta como leída) conservando el nº de serie de la etiqueta.

2. Crear el producto desde el escáner cuando el artículo existe en el maestro
   de Sage pero nunca se creó en Odoo (Sage tenía 0 unidades).
"""
import re

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import SQL

from .sage_expected import normalize_serial, sql_scan_reads_line
from .sage_library import article_parts
from .scan_rule import normalize_code

# Confusiones típicas al teclear un nº de serie: O/Q/0, I/L/1, S/5, B/8, Z/2.
_CONFUSED_FROM, _CONFUSED_TO = "OQILSBZ", "0011582"
_CONFUSED = str.maketrans(_CONFUSED_FROM, _CONFUSED_TO)
SIMILAR_MIN_LENGTH = 6
SIMILAR_MAX_CANDIDATES = 5
_NOT_ALNUM = re.compile(r"[^0-9A-Z]")
# Mismo "núcleo" que serial_core, en SQL (sin "%": va en consultas con parámetros).
_SQL_CORE = ("CASE WHEN left(l.serial_normalized, 2) = 'SN' AND length(l.serial_normalized) > 4 "
             "THEN COALESCE(NULLIF(ltrim(substr(l.serial_normalized, 3), '0'), ''), '0') "
             "ELSE l.serial_normalized END")


def serial_core(key):
    """Nº de serie normalizado sin el "SN" que unas veces va delante en Sage y
    otras en la etiqueta: los parecidos se buscan sobre esta forma."""
    if key.startswith("SN") and len(key) > 4:
        return key[2:].lstrip("0") or "0"
    return key


# En qué se diferencia el nº de serie de Sage del leído, dicho en llano, y
# qué se enseña primero: una errata de tecleo antes que "cambia un carácter",
# que es lo que pasa también entre dos equipos correlativos (…0014 y …0017).
SIMILAR_WHY = {
    "same": (0, "igual salvo el «SN» de delante"),
    "confused": (0, "se confunden letras y cifras (O/0, I/1, S/5…)"),
    "extra": (1, "en Sage sobra un carácter"),
    "missing": (1, "en Sage falta un carácter"),
    "swapped": (1, "dos caracteres cambiados de sitio"),
    "changed": (2, "cambia un carácter"),
}


def similar_kind(read, sage):
    """En qué se parecen el nº de serie leído y el de Sage (clave de
    SIMILAR_WHY), o False si no se parecen: un carácter de más, de menos o
    cambiado, dos vecinos intercambiados, o solo confusiones típicas."""
    if read == sage:
        return "same"
    la, lb = len(read), len(sage)
    if abs(la - lb) > 1:
        return False
    if la == lb:
        if read.translate(_CONFUSED) == sage.translate(_CONFUSED):
            return "confused"
        diff = [i for i in range(la) if read[i] != sage[i]]
        if len(diff) == 1:
            return "changed"
        if (len(diff) == 2 and diff[1] == diff[0] + 1 and read[diff[0]] == sage[diff[1]]
                and read[diff[1]] == sage[diff[0]]):
            return "swapped"
        return False
    short, long_ = (read, sage) if la < lb else (sage, read)
    i = 0
    while i < len(short) and short[i] == long_[i]:
        i += 1
    if short[i:] != long_[i + 1:]:
        return False
    return "extra" if lb > la else "missing"


def similar_serials(a, b):
    return bool(similar_kind(a, b))


class RmsStockCountScan(models.Model):
    _inherit = "rms.stock.count.scan"

    sage_match_state = fields.Selection(
        [("suggested", "Por confirmar"), ("confirmed", "Confirmada"), ("rejected", "Descartada")],
        string="Coincidencia probable con Sage", readonly=True, index="btree_not_null",
        help="La etiqueta no está en Sage pero se parece a un nº de serie de Sage sin leer.")
    sage_match_key = fields.Char(
        string="Nº de serie de Sage emparejado (normalizado)", readonly=True, index="btree_not_null")
    sage_match_serial = fields.Char(string="Nº de serie en Sage", readonly=True)
    sage_match_line_id = fields.Many2one(
        "rms.sage.stock.line", string="Línea de Sage emparejada", readonly=True, ondelete="set null")
    sage_match_candidates = fields.Json(string="Candidatas de Sage", readonly=True)
    sage_match_rejected = fields.Json(string="Candidatas descartadas", readonly=True)
    sage_match_user_id = fields.Many2one("res.users", string="Confirmado por (usuario)", readonly=True)
    sage_match_operator_id = fields.Many2one(
        "rms.stock.count.operator", string="Confirmado por (operario)", readonly=True, ondelete="set null")
    sage_match_date = fields.Datetime(string="Confirmado el", readonly=True)

    # ------------------------------------------------------------------
    # Claves para cruzar con Sage
    # ------------------------------------------------------------------

    def _sage_key(self):
        """Nº de serie normalizado con el que esta lectura se cruza con Sage:
        el de Sage si está emparejada, si no el de la etiqueta."""
        self.ensure_one()
        if self.sage_match_state == "confirmed" and self.sage_match_key:
            return self.sage_match_key
        return normalize_serial(self.lot_name)

    def _verdict_serial(self):
        self.ensure_one()
        if self.sage_match_state == "confirmed" and self.sage_match_key:
            return self.sage_match_key
        return self.lot_name or ""

    def _match_verdict(self, verdict):
        """Veredicto nuevo 'prob' (ámbar) mientras la pregunta está sin contestar."""
        self.ensure_one()
        if self.sage_match_state == "suggested":
            return dict(verdict, v="prob")
        return verdict

    def _match_payload(self):
        self.ensure_one()
        if not self.sage_match_state:
            return False
        payload = {"state": self.sage_match_state, "serial": self.sage_match_serial or ""}
        if self.sage_match_state == "suggested":
            payload["candidates"] = [
                {"key": c["key"], "serial": c["serial"], "product": c.get("product") or "",
                 "wh": c.get("wh") or "", "article": c.get("article") or "", "why": c.get("why") or ""}
                for c in (self.sage_match_candidates or [])]
        elif self.sage_match_state == "confirmed":
            payload["by"] = self.sage_match_operator_id.name or self.sage_match_user_id.name or ""
            payload["at"] = (fields.Datetime.context_timestamp(self, self.sage_match_date).strftime("%d/%m %H:%M")
                             if self.sage_match_date else "")
        return payload

    # ------------------------------------------------------------------
    # Búsqueda de nº de serie parecidos en Sage
    # ------------------------------------------------------------------

    @api.model
    def _similar_sage_candidates(self, operator, serial, exclude=()):
        """Existencias vigentes de Sage aún sin leer cuyo nº de serie se parece
        al leído. Prefiltro en SQL (longitud ±1 y principio o final iguales, o
        iguales salvo confusiones típicas) y comparación fina en Python."""
        key = normalize_serial(serial)
        core = serial_core(key)
        if len(key) < SIMILAR_MIN_LENGTH or len(core) < SIMILAR_MIN_LENGTH - 1:
            return []
        size = len(core)
        head = (size - 1) // 2
        tail = size - head - 1
        Line = self.env["rms.sage.stock.line"].sudo()
        Line.flush_model()
        cr = self.env.cr
        cr.execute(SQL(
            """SELECT x.id, x.serial_normalized, x.serial, x.product_id, x.sage_warehouse_id, x.article_code,
                      x.sage_company_code, x.warehouse_code, x.core
                 FROM (SELECT l.id, l.serial_normalized, l.serial, l.product_id, l.sage_warehouse_id,
                              l.article_code, l.sage_company_code, l.warehouse_code, """ + _SQL_CORE + """ AS core
                         FROM rms_sage_stock_line l
                        WHERE l.is_current AND l.stock_kind = 'stock' AND l.quantity > 0
                          AND l.serial_normalized <> '' AND l.product_id IS NOT NULL) x
                WHERE length(x.core) BETWEEN %s AND %s
                  AND (left(x.core, %s) = %s OR right(x.core, %s) = %s OR translate(x.core, %s, %s) = %s)""",
            size - 1, size + 1, head, core[:head], tail, core[size - tail:],
            _CONFUSED_FROM, _CONFUSED_TO, core.translate(_CONFUSED)))
        excluded = set(exclude) | {key}
        rows = [row + (similar_kind(core, row[8]),) for row in cr.fetchall() if row[1] not in excluded]
        rows = [row for row in rows if row[9]]
        if not rows:
            return []
        # Solo las que nadie ha leído todavía (en ningún recuento no cancelado).
        self.flush_model()
        cr.execute("""
            SELECT l.id FROM rms_sage_stock_line l
             WHERE l.id = ANY(%s) AND EXISTS (
                   SELECT 1 FROM rms_stock_count_scan sc
                     JOIN rms_stock_count_session ss ON ss.id = sc.session_id
                    WHERE """ + sql_scan_reads_line('sc', 'l') + """
                      AND sc.scan_type = 'serial' AND ss.state <> 'cancel'
                      AND NOT COALESCE(sc.ignored, FALSE)
                      AND (l.product_id IS NULL OR sc.product_id = l.product_id))""", ([row[0] for row in rows],))
        read = {row[0] for row in cr.fetchall()}
        rows = [row for row in rows if row[0] not in read]
        if not rows:
            return []
        here = set(operator.sudo()._progress_warehouses().ids)
        products = {p.id: p for p in self.env["product.product"].sudo().browse({row[3] for row in rows}).exists()}
        warehouses = {w.id: w for w in self.env["rms.sage.warehouse"].sudo().browse(
            {row[4] for row in rows if row[4]}).exists()}
        company = {"01": "RMS", "02": "Espacio", "03": "RJB"}
        candidates = {}
        for (line_id, line_key, line_serial, product_id, warehouse_id, article, company_code, wh_code,
             _core, why) in rows:
            product = products.get(product_id)
            if not product or product.tracking == "none":
                continue
            warehouse = warehouses.get(warehouse_id)
            candidate = {
                "id": line_id, "key": line_key, "serial": line_serial or line_key, "product_id": product_id,
                "product": product.display_name, "article": article or "",
                "wh": "%s %s" % (company.get(company_code, company_code or ""),
                                 (warehouse.name if warehouse else wh_code) or ""),
                "here": warehouse_id in here, "why": SIMILAR_WHY[why][1], "rank": SIMILAR_WHY[why][0],
            }
            previous = candidates.get((line_key, product_id))
            # El mismo nº de serie y producto en dos almacenes: una sola candidata (la de la nave).
            if not previous or (candidate["here"] and not previous["here"]):
                candidates[(line_key, product_id)] = candidate
        result = list(candidates.values())
        current = operator.current_product_id
        if current and operator.product_explicit and any(c["product_id"] == current.id for c in result):
            result = [c for c in result if c["product_id"] == current.id]
        if any(c["here"] for c in result):
            result = [c for c in result if c["here"]]
        result.sort(key=lambda c: (c["rank"], c["serial"], c["id"]))
        return result[:SIMILAR_MAX_CANDIDATES]

    @api.model
    def _classify_similar(self, operator, serial, base, brand_note=""):
        """Clasificación de una lectura que no está en Sage pero se parece a
        algo de Sage. None si no hay parecidos (se sigue como siempre)."""
        key = normalize_serial(serial)
        if len(key) < SIMILAR_MIN_LENGTH:
            return None
        session = operator.session_id
        # La misma etiqueta ya se emparejó (otro operario, otro recuento): se hereda.
        known = self.sudo().search([
            ("sage_match_state", "=", "confirmed"), ("serial_normalized", "=", key),
            ("scan_type", "=", "serial"), ("ignored", "=", False), ("session_id.state", "!=", "cancel"),
            ("product_id", "!=", False),
        ], order="id", limit=1)
        if known:
            return dict(
                base, scan_type="serial", product_id=known.product_id.id, lot_id=known.lot_id.id or False,
                lot_name=serial, is_new_lot=not known.lot_id, quantity=1.0,
                sage_match_state="confirmed", sage_match_key=known.sage_match_key,
                sage_match_serial=known.sage_match_serial, sage_match_line_id=known.sage_match_line_id.id or False,
                sage_match_user_id=known.sage_match_user_id.id or False,
                sage_match_operator_id=known.sage_match_operator_id.id or False,
                sage_match_date=known.sage_match_date,
                message="%s · %s ≈ Sage %s (emparejado antes por %s)%s" % (
                    known.product_id.display_name, serial, known.sage_match_serial,
                    known.sage_match_operator_id.name or known.sage_match_user_id.name or "otro operario",
                    brand_note),
            )
        # Lo que ya se descartó para esta etiqueta en este recuento no se vuelve a proponer.
        rejected = set()
        for scan in self.search([("session_id", "=", session.id), ("serial_normalized", "=", key),
                                 ("sage_match_state", "=", "rejected")]):
            rejected.update(scan.sage_match_rejected or [])
        candidates = self._similar_sage_candidates(operator, serial, exclude=rejected)
        if not candidates:
            return None
        vals = dict(base, scan_type="unknown", lot_name=serial, quantity=0.0,
                    sage_match_state="suggested", sage_match_candidates=candidates)
        if len(candidates) == 1:
            only = candidates[0]
            vals.update(
                product_id=only["product_id"], sage_match_key=only["key"], sage_match_serial=only["serial"],
                sage_match_line_id=only["id"],
                message="Se parece a %s de Sage (%s). ¿Es este?" % (only["serial"], only["product"]))
        else:
            vals["message"] = ("Se parece a %d nº de serie de Sage (%s): elige cuál es, o «Ninguna»."
                               % (len(candidates), ", ".join(c["serial"] for c in candidates)))
        return vals

    # ------------------------------------------------------------------
    # Acciones del operario: "Sí, es este" / "No, es otro"
    # ------------------------------------------------------------------

    def _match_result(self):
        self.ensure_one()
        return {"status": self.sage_match_state, "scan": self._scanner_payload()}

    def scanner_match_confirm(self, key=False, operator_id=False):
        """"Sí, es este": la lectura queda emparejada con esa línea de Sage y
        pasa a contar como leída. Repetir la llamada no cambia nada."""
        self.ensure_one()
        self.operator_id._check_counting()
        if self.sage_match_state == "confirmed":
            if key and key != self.sage_match_key:
                raise UserError("Esta lectura ya está emparejada con %s de Sage." % self.sage_match_serial)
            return self._match_result()
        if self.sage_match_state != "suggested":
            raise UserError("Esta lectura ya no tiene una sugerencia pendiente.")
        candidates = self.sage_match_candidates or []
        if not key and len(candidates) == 1:
            key = candidates[0]["key"]
        candidate = next((c for c in candidates if c["key"] == key), None)
        if not candidate:
            raise UserError("Elige uno de los nº de serie de Sage propuestos.")
        Line = self.env["rms.sage.stock.line"].sudo()
        line = Line.search([("is_current", "=", True), ("stock_kind", "=", "stock"), ("quantity", ">", 0),
                            ("serial_normalized", "=", key), ("product_id", "=", candidate["product_id"])],
                           order="id", limit=1)
        if not line:
            raise UserError("Sage ya no tiene %s en existencias: pulsa «No, es otro»." % candidate["serial"])
        product = line.product_id
        if product.tracking == "none":
            raise UserError("%s no se sigue por nº de serie en Odoo: actívalo en el producto." % product.display_name)
        Line.flush_model()
        self.flush_model()
        self.env.cr.execute("""
            SELECT sc.id FROM rms_sage_stock_line l, rms_stock_count_scan sc
              JOIN rms_stock_count_session ss ON ss.id = sc.session_id
             WHERE l.id = %s AND """ + sql_scan_reads_line('sc', 'l') + """
               AND sc.scan_type = 'serial' AND ss.state <> 'cancel' AND NOT COALESCE(sc.ignored, FALSE)
               AND sc.product_id = l.product_id AND sc.serial_normalized <> %s
             LIMIT 1""", (line.id, self.serial_normalized or ""))
        if self.env.cr.fetchone():
            raise UserError("El equipo %s de Sage ya se ha leído con otra etiqueta: pulsa «No, es otro»."
                            % line.serial)
        confirmer = self.env["rms.stock.count.operator"].browse(operator_id or []).exists()
        if not confirmer or confirmer.session_id != self.session_id:
            confirmer = self.operator_id
        serial = self.lot_name or self.code
        vals = {
            "scan_type": "serial", "product_id": product.id, "lot_name": serial, "quantity": 1.0,
            "sage_match_state": "confirmed", "sage_match_key": key, "sage_match_serial": line.serial,
            "sage_match_line_id": line.id, "sage_match_candidates": False,
            "sage_match_user_id": self.env.user.id, "sage_match_operator_id": confirmer.id,
            "sage_match_date": fields.Datetime.now(),
            "message": "%s · %s ≈ Sage %s (confirmado por %s)" % (
                product.display_name, serial, line.serial, confirmer.name),
        }
        # La misma etiqueta leída por otros operarios con la pregunta pendiente:
        # es el mismo equipo, queda emparejada igual (una lectura por operario).
        peers = self.search([
            ("id", "!=", self.id), ("sage_match_state", "=", "suggested"), ("ignored", "=", False),
            ("serial_normalized", "=", self.serial_normalized), ("session_id.state", "=", "counting"),
            ("operator_id", "!=", self.operator_id.id),
        ])
        for scan in self | peers.filtered(lambda s: any(c["key"] == key for c in (s.sage_match_candidates or []))):
            lot = self.env["stock.lot"].search([
                ("product_id", "=", product.id), ("name", "=", scan.lot_name or scan.code),
                ("company_id", "in", [scan.session_id.company_id.id, False])], limit=1)
            repeated = self.search_count([
                ("id", "!=", scan.id), ("operator_id", "=", scan.operator_id.id), ("scan_type", "=", "serial"),
                ("product_id", "=", product.id), ("serial_normalized", "=", scan.serial_normalized),
                ("ignored", "=", False)], limit=1)
            if repeated:
                # Ese operario ya la tenía contada (leída antes como alta): no se cuenta dos veces.
                scan.write({"scan_type": "ignored", "ignored": True, "quantity": 0.0,
                            "sage_match_state": False, "sage_match_candidates": False, "sage_match_key": False,
                            "message": "Repetida: %s ya estaba leída." % (scan.lot_name or scan.code)})
                continue
            scan.write(dict(vals, lot_name=scan.lot_name or scan.code, lot_id=lot.id or False,
                            is_new_lot=not lot))
        return self._match_result()

    def _match_reject_vals(self):
        self.ensure_one()
        keys = [c["key"] for c in (self.sage_match_candidates or [])]
        return {
            "sage_match_state": "rejected", "sage_match_key": False, "sage_match_serial": False,
            "sage_match_line_id": False, "sage_match_candidates": False,
            "sage_match_rejected": sorted(set((self.sage_match_rejected or []) + keys)),
            "sage_match_user_id": self.env.user.id, "sage_match_date": fields.Datetime.now(),
        }

    def scanner_match_reject(self, operator_id=False):
        """"No, es otro" / "Ninguna": la lectura se queda como hoy (no está en
        Sage: pide producto, o alta del producto leído/elegido) y esas
        candidatas no se le vuelven a proponer."""
        self.ensure_one()
        self.operator_id._check_counting()
        if self.sage_match_state == "rejected":
            return self._match_result()
        if self.sage_match_state != "suggested":
            raise UserError("Esta lectura ya está emparejada con Sage. Si no es correcto, bórrala y vuelve a leerla.")
        operator = self.operator_id
        confirmer = self.env["rms.stock.count.operator"].browse(operator_id or []).exists()
        vals = self._match_reject_vals()
        vals["sage_match_operator_id"] = (confirmer if confirmer.session_id == self.session_id else operator).id
        # Lo que habría salido sin la sugerencia (misma clasificación de siempre).
        plain = self.with_context(rms_no_similar=True)._classify(operator, self.code)
        plain.pop("_inherited_product", None)
        plain.pop("_camera_product_ids", None)
        plain.pop("location_id", None)
        if plain.get("scan_type") == "serial" and self.search_count([
                ("id", "!=", self.id), ("operator_id", "=", operator.id), ("scan_type", "=", "serial"),
                ("product_id", "=", plain.get("product_id")), ("ignored", "=", False),
                ("serial_normalized", "=", normalize_serial(plain.get("lot_name")))], limit=1):
            plain = {"scan_type": "ignored", "ignored": True, "quantity": 0.0,
                     "message": "Repetida: %s ya estaba leída." % (self.lot_name or self.code)}
        vals.update({"product_id": False, "lot_id": False, "is_new_lot": False, "quantity": 1.0})
        vals.update(plain)
        self.write(vals)
        self._compute_sage_suggestion()
        return self._match_result()


class RmsSageScannerProduct(models.Model):
    """Productos creados desde el escáner del recuento, para que Administración
    los revise (nombre, marca, seguimiento)."""

    _name = "rms.sage.scanner.product"
    _description = "Producto creado desde el escáner del recuento"
    _order = "create_date desc, id desc"
    _rec_name = "product_tmpl_id"

    product_tmpl_id = fields.Many2one("product.template", string="Producto", required=True, ondelete="cascade",
                                      readonly=True)
    default_code = fields.Char(related="product_tmpl_id.default_code", string="Referencia")
    categ_id = fields.Many2one(related="product_tmpl_id.categ_id", string="Marca")
    tracking = fields.Selection(related="product_tmpl_id.tracking", string="Seguimiento")
    article_code = fields.Char(string="Artículo Sage", readonly=True)
    article_name = fields.Char(string="Nombre en Sage", readonly=True)
    session_id = fields.Many2one("rms.stock.count.session", string="Recuento", readonly=True, ondelete="set null")
    operator_name = fields.Char(string="Operario", readonly=True)
    user_id = fields.Many2one("res.users", string="Creado por", readonly=True)
    by_quantity = fields.Boolean(string="Por cantidad (sin nº de serie)", readonly=True)
    reviewed = fields.Boolean(string="Revisado")


class RmsStockCountOperator(models.Model):
    _inherit = "rms.stock.count.operator"

    # ------------------------------------------------------------------
    # Catálogo de Sage: buscar un artículo y crear su producto
    # ------------------------------------------------------------------

    @api.model
    def _can_create_products(self):
        """Solo el responsable de inventario (el usuario REAL, no sudo). Los
        usuarios técnicos (p. ej. el de la sincronización con Sage) se pueden
        excluir por login en el parámetro
        rms_stock_count_session.no_scanner_create_logins (separados por comas)."""
        user = self.env.user
        if not user.has_group("stock.group_stock_manager") or user.share:
            return False
        blocked = self.env["ir.config_parameter"].sudo().get_param(
            "rms_stock_count_session.no_scanner_create_logins", "")
        return user.login not in {login.strip() for login in blocked.split(",") if login.strip()}

    def scanner_catalog_search(self, query="", limit=20):
        """"Buscar en el catálogo de Sage": artículos del maestro por código o
        nombre (sin distinguir mayúsculas, guiones ni el prefijo de marca) y,
        de cada uno, si ya tiene producto en Odoo."""
        self.ensure_one()
        self.session_id.check_access("read")
        limit = max(1, min(int(limit or 20), 50))
        result = {"can_create": self._can_create_products(), "query": query or "", "articles": []}
        words = [key for key in (_NOT_ALNUM.sub("", normalize_code(word)) for word in (query or "").split()[:6]) if key]
        if not words:
            return result
        Article = self.env["rms.sage.article"].sudo()
        Article.flush_model()
        where = [SQL(
            "(a.code_normalized LIKE %s OR regexp_replace(upper(concat_ws(' ', a.name, a.brand_name)), "
            "'[^0-9A-Z]', '', 'g') LIKE %s)", "%" + key + "%", "%" + key + "%") for key in words]
        self.env.cr.execute(SQL(
            """SELECT a.id FROM rms_sage_article a WHERE %s
                ORDER BY (COALESCE(a.state_prefix, 'nuevo') <> 'nuevo'), COALESCE(a.discontinued, FALSE),
                         length(a.code), a.code
                LIMIT %s""", SQL(" AND ").join(where), limit * 4))
        articles = Article.browse([row[0] for row in self.env.cr.fetchall()])
        Prepare = self.env["rms.sage.product.prepare"]
        prefixes = sorted(self.env["product.category"].sudo().search([("parent_id", "=", False)]).mapped("name"),
                          key=len, reverse=True)
        # Nombre de la marca como está en Odoo (sin crear categorías por buscar).
        brand_names = Article._brand_categories(articles.mapped("brand_name"), create=False)
        seen = set()
        for article in articles:
            model = article_parts(self.env, article.code, prefixes)[0].strip()
            model_key = normalize_code(model)
            if not model_key or model_key in seen:
                continue  # D-/2M- del mismo modelo: es el mismo producto
            seen.add(model_key)
            info = Prepare._article_template(article, model)
            template = info["template"]
            product = template.with_context(active_test=False).product_variant_ids[:1]
            result["articles"].append({
                "id": article.id, "code": article.code, "name": article.name or "", "model": model,
                "brand": (article.brand_categ_id.name or brand_names.get(article.brand_name, Article.brand_categ_id).name
                          or (article.brand_name or "").title()),
                "status": info["status"],  # missing | exists | archived | ambiguous
                "product_id": product.id if info["status"] == "exists" else False,
                "product_name": template.display_name if template else "",
            })
            if len(result["articles"]) >= limit:
                break
        return result

    def scanner_catalog_create(self, article_id, by_quantity=False):
        """"Crear este producto": lo crea como "Preparar productos" (misma
        lógica), sin duplicar nunca; queda como producto actual del operario.
        Si ya existía, lo elige; si está archivado, lo dice y no lo reactiva."""
        self.ensure_one()
        self._check_counting()
        if not self._can_create_products():
            raise UserError("Solo el responsable de inventario puede crear productos: avisa al responsable.")
        article = self.env["rms.sage.article"].sudo().browse(article_id or []).exists()
        if not article:
            raise UserError("No está en el catálogo de Sage. Apunta la referencia de la caja y avisa al responsable.")
        Prepare = self.env["rms.sage.product.prepare"]
        info = Prepare._article_template(article)
        template, status = info["template"], info["status"]
        if status == "archived":
            return {"status": "archived", "product_name": template.display_name, "product": False,
                    "message": "%s ya existe en Odoo pero está archivado: avisa al responsable para "
                               "reactivarlo. No se ha creado nada." % template.display_name}
        if status == "ambiguous":
            return {"status": "ambiguous", "product_name": "", "product": False,
                    "message": "Hay varios productos con la referencia %s: elige el correcto en el buscador "
                               "o avisa al responsable. No se ha creado nada." % info["model"]}
        if status == "missing":
            template = Prepare._create_from_article(article, by_quantity=bool(by_quantity))
            status = "created"
            template.sudo().message_post(body=(
                "Creado desde el escáner del recuento %s por %s, artículo Sage %s"
                % (self.session_id.name, self.env.user.name, article.code)))
            self.env["rms.sage.scanner.product"].sudo().create({
                "product_tmpl_id": template.id, "article_code": article.code, "article_name": article.name,
                "session_id": self.session_id.id, "operator_name": self.name, "user_id": self.env.user.id,
                "by_quantity": bool(by_quantity),
            })
        product = template.product_variant_ids[:1]
        self.current_product_id = product
        return {"status": status, "product": self._product_payload(product),
                "product_name": product.display_name, "message": "", "state": self._scanner_state()}
