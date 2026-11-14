# -*- coding: utf-8 -*-

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import SQL

from .scan_rule import normalize_code


class RmsStockCountOperator(models.Model):
    """Cada persona (o PDA) que participa en un recuento. Se identifica por
    nombre, no solo por usuario de Odoo, para que dos PDAs que compartan el
    mismo usuario cuenten como dos operarios distintos en el cruce."""

    _name = "rms.stock.count.operator"
    _description = "Operario de recuento cruzado"
    _order = "session_id, id"

    session_id = fields.Many2one(
        "rms.stock.count.session", string="Recuento", required=True, ondelete="cascade", index=True,
    )
    name = fields.Char(string="Operario", required=True)
    user_id = fields.Many2one(
        "res.users", string="Usuario", default=lambda self: self.env.user, readonly=True,
    )
    current_state_id = fields.Many2one(
        "product.state", string="Estado activo", compute="_compute_current_state_id",
        store=True, readonly=False,
    )

    @api.depends("session_id")
    def _compute_current_state_id(self):
        for operator in self:
            operator.current_state_id = operator.session_id.default_state_id

    search_mode = fields.Boolean(default=False)
    zone_closed = fields.Boolean(default=False)
    done = fields.Boolean(string="Ha terminado")
    current_location_id = fields.Many2one(
        "stock.location", string="Ubicación actual",
        help="Ubicación donde está escaneando ahora. Cambia al escanear la "
             "etiqueta de una ubicación o al elegirla en el escáner.",
    )
    current_product_id = fields.Many2one(
        "product.product", string="Producto actual",
        help="Último producto identificado (por su código de barras o elegido "
             "a mano). Los números de serie que aún no existen en Odoo se "
             "asignan a este producto.",
    )
    scan_ids = fields.One2many("rms.stock.count.scan", "operator_id", string="Lecturas")
    scan_count = fields.Integer(compute="_compute_scan_count", string="Nº de lecturas")

    _session_name_uniq = models.Constraint(
        "UNIQUE(session_id, name)",
        "Ya hay un operario con ese nombre en este recuento.",
    )

    @api.depends("scan_ids", "scan_ids.scan_type")
    def _compute_scan_count(self):
        for operator in self:
            operator.scan_count = len(operator.scan_ids.filtered(
                lambda s: s.scan_type in ("product", "serial", "unknown")
            ))

    def _check_counting(self):
        for operator in self:
            if operator.session_id.state != "counting":
                raise UserError(
                    "El recuento %s ya no está abierto para escanear." % operator.session_id.name
                )

    # ------------------------------------------------------------------
    # API del escáner (llamadas desde el cliente OWL)
    # ------------------------------------------------------------------

    @api.model
    def scanner_join(self, session_id, name):
        """Entra en el recuento con ese nombre: si ya existe un operario con
        ese nombre en la sesión se reutiliza (p. ej. al recargar la PDA)."""
        session = self.env["rms.stock.count.session"].browse(session_id).exists()
        if not session:
            raise UserError("El recuento ya no existe.")
        if session.state == "draft":
            session.action_start()
        if session.state != "counting":
            raise UserError("El recuento %s no está abierto para escanear." % session.name)
        name = (name or "").strip()
        if not name:
            raise UserError("Escribe tu nombre para empezar.")
        operator = self.search([("session_id", "=", session.id), ("name", "=", name)], limit=1)
        if not operator:
            operator = self.create({
                "session_id": session.id,
                "name": name,
                "current_location_id": session.location_id.id,
            })
        elif operator.done:
            operator.done = False
        return operator._scanner_state()

    @api.model
    def scanner_session_info(self, session_id):
        session = self.env["rms.stock.count.session"].browse(session_id).exists()
        if not session:
            raise UserError("El recuento ya no existe.")
        return {
            "id": session.id,
            "name": session.name,
            "state": session.state,
            "location_name": session.location_id.display_name,
            "operators": [
                {"id": op.id, "name": op.name, "done": op.done, "scan_count": op.scan_count}
                for op in session.operator_ids
            ],
            "default_name": self.env.user.name,
        }

    def scanner_state(self):
        self.ensure_one()
        return self._scanner_state()

    def _scanner_state(self, recent_limit=60):
        self.ensure_one()
        session = self.session_id
        recent = self.env["rms.stock.count.scan"].search(
            [("operator_id", "=", self.id), ("scan_type", "!=", "location")],
            limit=recent_limit,
        )
        return {
            "operator": {
                "id": self.id,
                "name": self.name,
                "done": self.done,
                "scan_count": self.scan_count,
                "search_mode": self.search_mode,
                "current_state_id": self.current_state_id.id,
            },
            "session": {
                "id": session.id,
                "name": session.name,
                "state": session.state,
                "location_name": session.location_id.display_name,
                "sage_mode": session.sage_mode,
            },
            "location": {
                "id": self.current_location_id.id,
                "name": self.current_location_id.display_name,
            } if self.current_location_id else False,
            "product_states": [
                {"id": state.id, "name": {"new": "Nuevo", "demo": "Demo", "ex_demo": "Ex-Demo", "second_hand": "2Mano"}[state.code],
                 "code": state.code}
                for state in self.env["product.state"].with_context(active_test=False).search([
                    ("code", "in", ["new", "demo", "ex_demo", "second_hand"]),
                ]).sorted(key=lambda state: ("new", "demo", "ex_demo", "second_hand").index(state.code))
            ],
            "product": self._product_payload(self.current_product_id),
            "others": [
                {"name": op.name, "scan_count": op.scan_count, "done": op.done}
                for op in session.operator_ids - self
            ],
            "recent": [scan.with_context(sage_batch=True)._scanner_payload() for scan in recent],
        }

    @api.model
    def _product_payload(self, product):
        if not product:
            return False
        return {
            "id": product.id,
            "name": product.display_name,
            "default_code": product.default_code or "",
            "barcode": product.barcode or "",
            "tracking": product.tracking,
        }

    # Veredictos que piden revisar algo (ámbar) en el marcador del escáner.
    _REVIEW_VERDICTS = ("est", "dep", "dup", "wh", "co")

    def _progress_warehouses(self):
        """Almacenes Sage enlazados a la ubicación donde se cuenta (la del
        operario o la del recuento): la misma, una de dentro o una de fuera."""
        self.ensure_one()
        location = self.current_location_id or self.session_id.location_id
        if not location:
            return self.env["rms.sage.warehouse"]
        path = location.parent_path or ""
        Warehouse = self.env["rms.sage.warehouse"].sudo()
        warehouses = Warehouse.search([("location_id", "!=", False), ("alias_of_id", "=", False)])
        found = warehouses.filtered(lambda w: w.location_id.parent_path and (
            w.location_id.parent_path.startswith(path) or path.startswith(w.location_id.parent_path)))
        # Misma nave física, las 3 empresas: RMS7 / ET7 / RJB7 = Sevilla.
        sites = set(found.mapped("site_number")) - {0}
        if sites:
            found |= warehouses.filtered(lambda w: w.site_number in sites)
        return found

    def scanner_progress(self):
        """Marcador fijo del escáner: avance del almacén Sage donde se cuenta
        (contados / faltan, sin lo que Sage tiene en depósito en clientes) y
        lo que este recuento ha encontrado fuera de Sage o para revisar."""
        self.ensure_one()
        session = self.session_id
        session.check_access("read")
        warehouses = self._progress_warehouses()
        # Un nombre por nave (las 3 empresas de Sevilla son "Sevilla (A.7)").
        names = list(dict.fromkeys(
            "%s (%s)" % (w.name, w.code) if w.name != w.code else w.code
            for w in warehouses.sorted(lambda w: (w.sage_company_code, w.code))))
        result = {
            "site": " + ".join(names[:3]) + (" + %d más" % (len(names) - 3) if len(names) > 3 else ""),
            "has_sage": bool(warehouses),
            "total": 0, "counted": 0, "pending": 0,
        }
        if warehouses:
            self.env["rms.sage.stock.line"].sudo().flush_model()
            self.env["rms.stock.count.scan"].flush_model()
            self.env.cr.execute("""
                SELECT count(*),
                       count(*) FILTER (WHERE EXISTS (
                           SELECT 1 FROM rms_stock_count_scan sc
                             JOIN rms_stock_count_session ss ON ss.id = sc.session_id
                            WHERE sc.serial_normalized = l.serial_normalized
                              AND sc.scan_type = 'serial'
                              AND ss.state <> 'cancel'
                              AND NOT COALESCE(sc.ignored, FALSE)
                              AND (l.product_id IS NULL OR sc.product_id = l.product_id)))
                  FROM rms_sage_stock_line l
                 WHERE l.is_current AND l.stock_kind = 'stock' AND l.quantity > 0
                   AND COALESCE(l.serial_normalized, '') <> ''
                   AND NOT COALESCE(l.in_deposit, FALSE)
                   AND l.sage_warehouse_id = ANY(%s)
            """, (warehouses.ids,))
            total, counted = self.env.cr.fetchone()
            result.update(total=total, counted=counted, pending=total - counted)
        Scan = self.env["rms.stock.count.scan"]
        scans = Scan.search([("session_id", "=", session.id), ("ignored", "=", False),
                             ("scan_type", "in", ("serial", "unknown"))])
        serials = scans.filtered(lambda s: s.scan_type == "serial" and s.lot_name)
        verdicts = Scan._sage_verdict([s.lot_name for s in serials], session, [s.product_id.id for s in serials],
                                      [s.product_state_id.code for s in serials]) if serials else []
        kinds = [v.get("v") for v in verdicts]
        result.update(
            not_in_sage=kinds.count("none"),
            review=sum(kinds.count(kind) for kind in self._REVIEW_VERDICTS)
            + len(scans.filtered(lambda s: s.scan_type == "unknown")),
            mine=self.scan_count,
        )
        return result

    _SAGE_STATE_TO_ODOO = {"nuevo": "new", "demo": "demo", "2mano": "second_hand"}
    _SAGE_STATE_NAME = {"nuevo": "Nuevo", "demo": "Demo", "2mano": "2Mano"}

    def scanner_sage_search(self, query="", limit=40):
        """Equipos de Sage del almacén donde se cuenta que AÚN no se han
        contado (para mesas en flycase sin pegatina): se buscan por modelo,
        nombre, artículo o los últimos dígitos del nº de serie."""
        self.ensure_one()
        self.session_id.check_access("read")
        warehouses = self._progress_warehouses()
        where = [SQL("l.is_current AND l.stock_kind = 'stock' AND l.quantity > 0"),
                 SQL("COALESCE(l.serial_normalized, '') <> '' AND NOT COALESCE(l.in_deposit, FALSE)")]
        if warehouses:
            where.append(SQL("l.sage_warehouse_id = ANY(%s)", warehouses.ids))
        else:
            where.append(SQL("l.company_id = %s", self.session_id.company_id.id))
        for word in (query or "").split():
            key = normalize_code(word)
            if not key:
                continue
            where.append(SQL(
                "(l.serial_normalized LIKE %s OR regexp_replace(upper(COALESCE(l.article_code, '') || ' ' || "
                "COALESCE(l.article_name, '') || ' ' || COALESCE(l.model_code, '')), '[^0-9A-Z]', '', 'g') LIKE %s)",
                "%" + key.lstrip("0") + "%", "%" + key + "%"))
        self.env["rms.sage.stock.line"].sudo().flush_model()
        self.env["rms.stock.count.scan"].flush_model()
        self.env.cr.execute(SQL("""
            SELECT l.id, l.article_code, l.article_name, l.model_code, l.serial, l.state,
                   l.sage_company_code, COALESCE(w.code, l.warehouse_code), l.product_id
              FROM rms_sage_stock_line l
              LEFT JOIN rms_sage_warehouse w ON w.id = l.sage_warehouse_id
             WHERE %s
               AND NOT EXISTS (
                   SELECT 1 FROM rms_stock_count_scan sc
                     JOIN rms_stock_count_session ss ON ss.id = sc.session_id
                    WHERE sc.serial_normalized = l.serial_normalized
                      AND sc.scan_type = 'serial' AND ss.state <> 'cancel'
                      AND NOT COALESCE(sc.ignored, FALSE)
                      AND (l.product_id IS NULL OR sc.product_id = l.product_id))
             ORDER BY l.article_code, l.serial_normalized
             LIMIT %s""", SQL(" AND ").join(where), max(1, min(int(limit or 40), 100))))
        rows = self.env.cr.fetchall()
        products = {p.id: p for p in self.env["product.product"].browse({r[8] for r in rows if r[8]}).exists()}
        return [{
            "id": r[0], "article": r[1] or "", "name": r[2] or "", "model": r[3] or "", "serial": r[4] or "",
            "state": r[5] or "nuevo", "state_name": self._SAGE_STATE_NAME.get(r[5], "Nuevo"),
            "site": "%s %s" % ({"01": "RMS", "02": "Espacio", "03": "RJB"}.get(r[6], r[6] or ""), r[7] or ""),
            "product_id": r[8] or False,
            "product_name": products[r[8]].display_name if r[8] in products else "",
        } for r in rows]

    def scanner_sage_print_and_count(self, line_id, state_id=False):
        """Mesa sin pegatina elegida en la lista de Sage: se cuenta como si se
        hubiera escaneado su nº de serie (con el estado de Sage salvo que se
        elija otro) y se imprime su etiqueta en el mismo paso."""
        self.ensure_one()
        self._check_counting()
        line = self.env["rms.sage.stock.line"].sudo().browse(line_id).exists()
        if not line or not line.is_current or line.stock_kind != "stock" or not line.serial:
            raise UserError("Ese equipo ya no está en la exportación de Sage vigente.")
        if not line.product_id:
            if not self.env.user.has_group("stock.group_stock_manager"):
                raise UserError("El artículo %s de Sage no tiene producto en Odoo: asígnalo en "
                                "Inventario Sage > Artículos sin producto." % line.article_code)
            self.env["rms.sage.product.prepare"].create({"line_ids": [(6, 0, line.ids)]}).action_create_products()
            line.invalidate_recordset(["product_id"])
            if not line.product_id:
                raise UserError("No se pudo crear el producto de %s: asígnalo en Artículos sin producto." % line.article_code)
        product = line.product_id
        if product.tracking == "none":
            raise UserError("%s no se sigue por nº de serie en Odoo: actívalo en el producto." % product.display_name)
        state = (self._scanner_product_state(state_id) if state_id else
                 self.env["product.state"].search([("code", "=", self._SAGE_STATE_TO_ODOO.get(line.state, "new"))], limit=1))
        location = self.current_location_id or self.session_id.location_id
        Scan = self.env["rms.stock.count.scan"]
        lot = self.env["stock.lot"].search([("product_id", "=", product.id), ("name", "=", line.serial)], limit=1)
        classification = {
            "location_id": location.id, "scan_type": "serial", "product_id": product.id,
            "lot_id": lot.id or False, "lot_name": line.serial, "is_new_lot": not lot, "quantity": 1.0,
            "message": "Contado desde la lista de Sage (sin pegatina): %s · %s" % (product.display_name, line.serial),
        }
        result = Scan.with_context(scanner_product_state_id=state.id)._scanner_register(
            self.id, line.serial, classification=classification)
        scan = Scan.browse(result["scan"]["id"])
        action = scan.scanner_print_label()
        return {"status": result["status"], "scan": scan._scanner_payload(), "action": action,
                "state": self._scanner_state()}

    def scanner_set_location(self, location_id):
        self.ensure_one()
        self._check_counting()
        location = self.env["stock.location"].browse(location_id).exists()
        if not location or not location._child_of(self.session_id.location_id):
            raise UserError("Esa ubicación no está dentro de la ubicación del recuento.")
        self.current_location_id = location
        return self._scanner_state()

    def scanner_set_state(self, state_id):
        self.ensure_one()
        self._check_counting()
        self.current_state_id = self._scanner_product_state(state_id)
        return self._scanner_state()

    @api.model
    def _scanner_product_state(self, state_id):
        state = self.env["product.state"].browse(state_id).exists()
        if len(state) != 1 or state.code not in ("new", "demo", "ex_demo", "second_hand"):
            raise UserError("Elige Nuevo, Demo, Ex-Demo o 2Mano.")
        return state

    def scanner_set_product(self, product_id):
        self.ensure_one()
        self._check_counting()
        self.current_product_id = self.env["product.product"].browse(product_id).exists() or False
        return self._scanner_state()

    def scanner_replacement_label(self):
        """Asistente de etiqueta sustituta (nº de serie grabado en el
        equipo, etiqueta dañada, caja con varios equipos), con el producto
        actual ya puesto si lleva seguimiento."""
        self.ensure_one()
        self._check_counting()
        product = self.current_product_id
        return {
            "type": "ir.actions.act_window",
            "name": "Etiqueta sustituta",
            "res_model": "rms.lot.label.wizard",
            "view_mode": "form",
            "views": [[False, "form"]],
            "target": "new",
            "context": {
                "default_count_operator_id": self.id,
                "default_product_state_id": self.current_state_id.id,
                "default_product_id": product.id if product and product.tracking != "none" else False,
            },
        }

    def scanner_finish(self):
        self.ensure_one()
        return self.scanner_close_zone()

    def scanner_close_zone(self):
        self.ensure_one()
        self._check_counting()
        self.write({'done': True, 'zone_closed': True, 'search_mode': False})
        return self._scanner_missing()

    def _scanner_missing(self):
        self.ensure_one()
        if not self.zone_closed:
            raise UserError('Termina primero el recorrido para ver los faltantes.')
        session = self.session_id
        seen = set()
        counted_products = set()
        from .sage_expected import normalize_serial
        for scan in session.scan_ids.filtered(lambda s: not s.ignored and s.scan_type in ('serial', 'product')):
            if scan.product_id:
                counted_products.add(scan.product_id.id)
                if scan.lot_name:
                    seen.add((scan.product_id.id, normalize_serial(scan.lot_name)))
        groups = {}
        lines = session._sage_lines()
        # Reserve exact product matches before allocating unmatched serials.
        lines = lines.sorted(key=lambda line: (line.product_id.id, line.serial_normalized) not in seen)
        # Índice por nº de serie: evita recorrer 'seen' en cada línea (cuadrático).
        seen_by_serial = {}
        for item in seen:
            seen_by_serial.setdefault(item[1], set()).add(item)
        for line in lines:
            if line.serial_normalized:
                key = (line.product_id.id, line.serial_normalized)
                bucket = seen_by_serial.get(line.serial_normalized)
                match = key if key in seen else (next(iter(bucket)) if bucket else None)
                if match:
                    seen.remove(match)
                    seen_by_serial[match[1]].discard(match)
                    continue
            elif line.product_id.id in counted_products:
                continue
            key = (line.product_id.id, line.model_code, bool(line.serial_normalized))
            group = groups.setdefault(key, {'model': line.product_id.display_name or line.model_code,
                                           'serials': [], 'count_by_quantity': not bool(line.serial_normalized)})
            if line.serial and line.serial not in group['serials']:
                group['serials'].append(line.serial)
        missing = list(groups.values())
        sites = ', '.join('%s (%s)' % (w.name, w.code) if w.name and w.name != w.code else w.code
                          for w in session.sage_warehouse_ids)
        return {'missing': missing, 'site': sites or session.location_id.display_name,
                'count': sum(len(row['serials']) if not row['count_by_quantity'] else 1 for row in missing)}

    def scanner_start_search(self):
        self.ensure_one()
        self._check_counting()
        if not self.zone_closed:
            raise UserError('Cierra primero la zona.')
        self.write({'search_mode': True, 'done': False})
        return self._scanner_state()

    def scanner_search_products(self, query, limit=20):
        self.ensure_one()
        query = (query or "").strip()
        domain = [("is_storable", "=", True)]
        if query:
            domain += [
                "|", "|",
                ("name", "ilike", query),
                ("default_code", "ilike", query),
                ("barcode", "ilike", query),
            ]
        products = self.env["product.product"].search(domain, limit=limit, order="name")
        return [self._product_payload(p) for p in products]

    def scanner_search_locations(self, query, limit=20):
        self.ensure_one()
        domain = [
            ("usage", "=", "internal"),
            ("id", "child_of", self.session_id.location_id.id),
        ]
        query = (query or "").strip()
        if query:
            domain.append(("complete_name", "ilike", query))
        locations = self.env["stock.location"].search(domain, limit=limit, order="complete_name")
        return [{"id": loc.id, "name": loc.complete_name} for loc in locations]
