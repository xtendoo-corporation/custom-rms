# -*- coding: utf-8 -*-

from odoo import api, fields, models
from odoo.exceptions import UserError


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
        for line in lines:
            if line.serial_normalized:
                key = (line.product_id.id, line.serial_normalized)
                match = key if key in seen else next((k for k in seen if k[1] == line.serial_normalized), None)
                if match:
                    seen.remove(match)
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
