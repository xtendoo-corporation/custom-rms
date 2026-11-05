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
            "product": self._product_payload(self.current_product_id),
            "others": [
                {"name": op.name, "scan_count": op.scan_count, "done": op.done}
                for op in session.operator_ids - self
            ],
            "recent": [scan._scanner_payload() for scan in recent],
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
                "default_product_id": product.id if product and product.tracking != "none" else False,
            },
        }

    def scanner_finish(self):
        self.ensure_one()
        self.done = True
        return True

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
