# -*- coding: utf-8 -*-

from collections import defaultdict

from odoo import api, fields, models
from odoo.exceptions import UserError


class RmsStockCountSession(models.Model):
    """Recuento cruzado: varias personas recorren el mismo almacén (cada una
    por su lado) escaneando todo lo que ven. Cada lectura se guarda en el
    servidor al momento (rms.stock.count.scan), y al cerrar el recuento se
    genera el cruce (rms.stock.count.line): qué vieron todos, qué vio solo
    una parte y qué esperaba Odoo que nadie escaneó."""

    _name = "rms.stock.count.session"
    _description = "Sesión de recuento cruzado"
    _order = "id desc"
    _check_company_auto = True

    name = fields.Char(
        string="Referencia", required=True, copy=False, readonly=True, default="Nuevo",
    )
    company_id = fields.Many2one(
        "res.company", string="Compañía", required=True, default=lambda self: self.env.company,
    )
    location_id = fields.Many2one(
        "stock.location",
        string="Ubicación a recontar",
        required=True,
        check_company=True,
        domain="[('usage', '=', 'internal')]",
        default=lambda self: self._default_location(),
        help="Se cuenta esta ubicación y todas sus sububicaciones. Lo que "
             "Odoo tenga en stock aquí y nadie escanee aparecerá en el cruce "
             "como 'Nadie lo escaneó'.",
    )
    state = fields.Selection(
        [
            ("draft", "Preparada"),
            ("counting", "En recuento"),
            ("review", "En revisión"),
            ("done", "Volcada a inventario"),
            ("cancel", "Cancelada"),
        ],
        string="Estado", default="draft", required=True, copy=False,
    )
    note = fields.Text(string="Notas")
    operator_ids = fields.One2many(
        "rms.stock.count.operator", "session_id", string="Operarios",
    )
    scan_ids = fields.One2many(
        "rms.stock.count.scan", "session_id", string="Lecturas",
    )
    unknown_scan_ids = fields.One2many(
        "rms.stock.count.scan", "session_id",
        string="Códigos sin identificar",
        domain=[("scan_type", "=", "unknown"), ("ignored", "=", False)],
    )
    line_ids = fields.One2many(
        "rms.stock.count.line", "session_id", string="Cruce",
    )
    date_start = fields.Datetime(string="Inicio", readonly=True, copy=False)
    date_review = fields.Datetime(string="Fin del recuento", readonly=True, copy=False)
    date_done = fields.Datetime(string="Volcado", readonly=True, copy=False)

    operator_count = fields.Integer(compute="_compute_counters", string="Nº operarios")
    scan_count = fields.Integer(compute="_compute_counters", string="Nº lecturas")
    unknown_count = fields.Integer(compute="_compute_counters", string="Sin identificar")
    line_match_count = fields.Integer(compute="_compute_counters", string="Coinciden")
    line_partial_count = fields.Integer(compute="_compute_counters", string="Solo una parte")
    line_missing_count = fields.Integer(compute="_compute_counters", string="Nadie lo escaneó")
    line_unexpected_count = fields.Integer(compute="_compute_counters", string="No esperados")
    line_qty_diff_count = fields.Integer(compute="_compute_counters", string="Cantidades distintas")

    @api.model
    def _default_location(self):
        warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1
        )
        return warehouse.lot_stock_id

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "Nuevo") == "Nuevo":
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("rms.stock.count.session") or "Nuevo"
                )
        return super().create(vals_list)

    @api.depends("operator_ids", "scan_ids", "scan_ids.scan_type", "scan_ids.ignored",
                 "line_ids", "line_ids.status")
    def _compute_counters(self):
        for session in self:
            session.operator_count = len(session.operator_ids)
            session.scan_count = len(session.scan_ids.filtered(
                lambda s: s.scan_type in ("product", "serial")
            ))
            session.unknown_count = len(session.scan_ids.filtered(
                lambda s: s.scan_type == "unknown" and not s.ignored
            ))
            statuses = session.line_ids.mapped("status")
            session.line_match_count = statuses.count("match")
            session.line_partial_count = statuses.count("partial")
            session.line_missing_count = statuses.count("missing")
            session.line_unexpected_count = statuses.count("unexpected")
            session.line_qty_diff_count = statuses.count("qty_diff")

    def unlink(self):
        if any(s.state == "done" for s in self):
            raise UserError("No se puede borrar un recuento que ya se ha volcado al inventario.")
        return super().unlink()

    # ------------------------------------------------------------------
    # Flujo de estados
    # ------------------------------------------------------------------

    def action_start(self):
        for session in self:
            if session.state != "draft":
                continue
            session.write({"state": "counting", "date_start": fields.Datetime.now()})

    def action_open_scanner(self):
        self.ensure_one()
        if self.state == "draft":
            self.action_start()
        if self.state != "counting":
            raise UserError("Solo se puede escanear mientras el recuento está 'En recuento'.")
        return {
            "type": "ir.actions.client",
            "tag": "rms_stock_count_session.scan",
            "name": "Recuento %s" % self.name,
            "context": {"active_id": self.id, "active_model": self._name},
        }

    def action_close_counting(self):
        for session in self:
            if session.state != "counting":
                raise UserError("Solo se puede cerrar un recuento que está 'En recuento'.")
            session.write({"state": "review", "date_review": fields.Datetime.now()})
            session.operator_ids.write({"done": True})
            session._build_reconciliation()

    def action_reopen(self):
        for session in self:
            if session.state != "review":
                raise UserError("Solo se puede reabrir un recuento que está 'En revisión'.")
            session.write({"state": "counting"})
            session.operator_ids.write({"done": False})

    def action_rebuild(self):
        for session in self:
            if session.state != "review":
                raise UserError("El cruce solo se puede regenerar en revisión.")
            session._build_reconciliation()

    def action_cancel(self):
        for session in self:
            if session.state == "done":
                raise UserError("Este recuento ya se ha volcado al inventario.")
            session.state = "cancel"

    def action_reset_draft(self):
        for session in self:
            if session.state != "cancel":
                continue
            session.state = "draft"

    def action_view_lines(self):
        self.ensure_one()
        status = self.env.context.get("count_line_status")
        domain = [("session_id", "=", self.id)]
        if status:
            domain.append(("status", "=", status))
        return {
            "type": "ir.actions.act_window",
            "name": "Cruce %s" % self.name,
            "res_model": "rms.stock.count.line",
            "view_mode": "list",
            "domain": domain,
            "context": {"default_session_id": self.id},
        }

    # ------------------------------------------------------------------
    # Cruce de lecturas
    # ------------------------------------------------------------------

    def _get_expected_quants(self):
        """Stock que Odoo cree que hay dentro de la ubicación recontada."""
        self.ensure_one()
        return self.env["stock.quant"].search([
            ("location_id", "child_of", self.location_id.id),
            ("location_id.usage", "=", "internal"),
            ("quantity", ">", 0),
            ("product_id.is_storable", "=", True),
        ])

    def _build_reconciliation(self):
        """Regenera las líneas del cruce a partir de las lecturas.

        - Productos con número de serie: una línea por número de serie. Se
          considera contado (1) si lo escaneó al menos un operario; el
          estado dice si lo vieron todos o solo una parte.
        - Resto (sin seguimiento o por lotes): una línea por producto + lote
          + ubicación. Cada operario cuenta por su lado; la cantidad
          propuesta es la MAYOR de las cantidades contadas (la idea es que
          lo que se le pasó a uno lo vio el otro), y si no coinciden se
          marca 'Cantidades distintas' para que alguien lo revise.
        - El desacuerdo entre operarios manda sobre la comparación con
          Odoo: algo nuevo (que Odoo no tenía) que solo vio una persona
          sale como 'Solo lo vio una parte', no como 'Nuevo'. La columna
          'En Odoo' (0) ya indica que no estaba.
        - Lo que Odoo tiene en stock en la ubicación y nadie escaneó sale
          como 'Nadie lo escaneó', sin marcar para volcar (hay que decidir
          a mano si de verdad falta).
        """
        Line = self.env["rms.stock.count.line"]
        for session in self:
            session.line_ids.unlink()
            operators = session.operator_ids
            n_operators = len(operators)
            scans = session.scan_ids.filtered(
                lambda s: s.scan_type in ("product", "serial") and not s.ignored
            )

            # clave -> {operator_id: qty}, clave -> {location_id: veces}
            qty_by_key = defaultdict(lambda: defaultdict(float))
            loc_votes = defaultdict(lambda: defaultdict(int))
            for scan in scans:
                product = scan.product_id
                if product.tracking == "serial":
                    key = (product.id, scan.lot_name or "", False)
                else:
                    key = (product.id, scan.lot_name or "", scan.location_id.id)
                qty_by_key[key][scan.operator_id.id] += scan.quantity or 1.0
                loc_votes[key][scan.location_id.id] += 1

            expected = defaultdict(float)
            expected_loc = {}
            for quant in session._get_expected_quants():
                lot_name = quant.lot_id.name or ""
                if quant.product_id.tracking == "serial":
                    key = (quant.product_id.id, lot_name, False)
                    expected_loc[key] = quant.location_id.id
                else:
                    key = (quant.product_id.id, lot_name, quant.location_id.id)
                expected[key] += quant.quantity

            vals_list = []
            operator_names = {op.id: op.name for op in operators}
            for key in set(qty_by_key) | set(expected):
                product_id, lot_name, location_id = key
                product = self.env["product.product"].browse(product_id)
                per_operator = qty_by_key.get(key, {})
                seen_by = [op_id for op_id, qty in per_operator.items() if qty > 0]
                expected_qty = expected.get(key, 0.0)

                if location_id is False:
                    # Número de serie: la ubicación es donde se escaneó (la
                    # más votada si los operarios no coinciden) o, si nadie
                    # lo vio, donde Odoo cree que está.
                    votes = loc_votes.get(key)
                    if votes:
                        location_id = max(votes.items(), key=lambda kv: kv[1])[0]
                    else:
                        location_id = expected_loc.get(key)
                    locations_seen = len(votes) if votes else 0
                    counted_qty = 1.0 if seen_by else 0.0
                    if not seen_by:
                        status = "missing"
                    elif len(seen_by) < n_operators:
                        status = "partial"
                    elif not expected_qty:
                        status = "unexpected"
                    else:
                        status = "match"
                else:
                    locations_seen = 1 if seen_by else 0
                    quantities = [per_operator.get(op.id, 0.0) for op in operators]
                    counted_qty = max(quantities) if quantities else 0.0
                    if not seen_by:
                        status = "missing"
                    elif len(seen_by) < n_operators:
                        status = "partial"
                    elif len(set(quantities)) > 1:
                        status = "qty_diff"
                    elif not expected_qty:
                        status = "unexpected"
                    else:
                        status = "match"

                lot = False
                if lot_name and product.tracking != "none":
                    lot = self.env["stock.lot"].search([
                        ("product_id", "=", product_id),
                        ("name", "=", lot_name),
                        ("company_id", "in", [session.company_id.id, False]),
                    ], limit=1)

                vals_list.append({
                    "session_id": session.id,
                    "product_id": product_id,
                    "lot_name": lot_name or False,
                    "lot_id": lot.id if lot else False,
                    "location_id": location_id or session.location_id.id,
                    "expected_qty": expected_qty,
                    "counted_qty": counted_qty,
                    "operator_seen_count": len(seen_by),
                    "operator_total": n_operators,
                    "seen_by": ", ".join(sorted(operator_names.get(o, "?") for o in seen_by)),
                    "qty_by_operator": " · ".join(
                        "%s: %g" % (op.name, per_operator.get(op.id, 0.0)) for op in operators
                    ) if product.tracking != "serial" else False,
                    "location_mismatch": locations_seen > 1,
                    "status": status,
                    "to_apply": status != "missing",
                })
            Line.create(vals_list)

    # ------------------------------------------------------------------
    # Volcado a Inventario físico
    # ------------------------------------------------------------------

    def action_apply_to_inventory(self):
        """Vuelca las líneas marcadas a Inventario físico (cantidad
        'Contada' de stock.quant). Igual que el escaneo existente, NO pulsa
        'Aplicar': las diferencias quedan pendientes en Inventario físico
        para que el responsable las revise y las aplique."""
        Lot = self.env["stock.lot"]
        Quant = self.env["stock.quant"].with_context(inventory_mode=True)
        for session in self:
            if session.state != "review":
                raise UserError("Solo se puede volcar un recuento que está 'En revisión'.")
            for line in session.line_ids.filtered("to_apply"):
                product = line.product_id
                lot = line.lot_id
                if product.tracking != "none" and line.lot_name and not lot:
                    lot = Lot.search([
                        ("product_id", "=", product.id),
                        ("name", "=", line.lot_name),
                        ("company_id", "in", [session.company_id.id, False]),
                    ], limit=1) or Lot.create({
                        "product_id": product.id,
                        "name": line.lot_name,
                        "company_id": session.company_id.id,
                    })
                    line.lot_id = lot
                if product.tracking != "none" and not lot:
                    raise UserError(
                        "La línea de %s no tiene número de serie/lote: corrígela o "
                        "desmárcala antes de volcar." % product.display_name
                    )

                if product.tracking == "serial" and line.counted_qty > 0:
                    # Un número de serie solo puede estar en un sitio: si Odoo
                    # lo tenía en otra ubicación del recuento, esa otra queda
                    # contada a 0 (se ha encontrado aquí).
                    others = Quant.search([
                        ("product_id", "=", product.id),
                        ("lot_id", "=", lot.id),
                        ("location_id", "child_of", session.location_id.id),
                        ("location_id", "!=", line.location_id.id),
                        ("quantity", ">", 0),
                    ])
                    others.write({"inventory_quantity": 0, "inventory_quantity_set": True})

                # En modo inventario, create() reutiliza el quant que ya
                # exista para producto + ubicación + lote y le pone la
                # cantidad contada.
                quant = Quant.create({
                    "product_id": product.id,
                    "location_id": line.location_id.id,
                    "lot_id": lot.id if lot else False,
                    "inventory_quantity": line.counted_qty,
                })
                # Contar 0 (falta) no cambia el valor por defecto del campo y
                # no marcaría la línea como contada: se fuerza.
                quant.inventory_quantity_set = True
            session.write({"state": "done", "date_done": fields.Datetime.now()})
        return {
            "type": "ir.actions.act_window",
            "name": "Inventario físico",
            "res_model": "stock.quant",
            "view_mode": "list",
            "domain": [
                ("location_id", "child_of", self[:1].location_id.id),
                ("inventory_quantity_set", "=", True),
            ],
            "context": {"inventory_mode": True},
        } if len(self) == 1 else True
