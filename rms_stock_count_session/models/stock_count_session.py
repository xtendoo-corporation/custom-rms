# -*- coding: utf-8 -*-

from collections import defaultdict
import json
import re

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
    default_state_id = fields.Many2one(
        "product.state", string="Estado por defecto",
        default=lambda self: self.env["product.state"].search([("code", "=", "new")], limit=1),
    )
    counting_date = fields.Date(string="Fecha de recuento", help="Vacío: fecha actual al volcar.")
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
            preserved = {}
            for old in session.line_ids:
                key = old.reconciliation_key or json.dumps([
                    old.product_id.id, old.lot_name or "",
                    False if old.product_id.tracking == "serial" else old.location_id.id,
                ])
                preserved[key] = dict(old.review_overrides or {})
            session.line_ids.unlink()
            operators = session.operator_ids
            n_operators = len(operators)
            scans = session.scan_ids.filtered(
                lambda s: s.scan_type in ("product", "serial") and not s.ignored
            )

            # clave -> {operator_id: qty}, clave -> {location_id: veces}
            qty_by_key = defaultdict(lambda: defaultdict(float))
            loc_votes = defaultdict(lambda: defaultdict(int))
            state_votes = defaultdict(lambda: defaultdict(list))
            for scan in scans:
                product = scan.product_id
                if product.tracking == "serial":
                    key = (product.id, scan.lot_name or "", False)
                else:
                    key = (product.id, scan.lot_name or "", scan.location_id.id)
                qty_by_key[key][scan.operator_id.id] += scan.quantity or 1.0
                loc_votes[key][scan.location_id.id] += 1
                if scan.product_state_id:
                    state_votes[key][scan.product_state_id.id].append((scan.scanned_at, scan.id))

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

                votes = state_votes.get(key, {})
                state_id = max(votes, key=lambda state: (len(votes[state]), max(votes[state]))) if votes else (
                    lot.product_state_id.id if lot else session.default_state_id.id
                )
                source_key = json.dumps(list(key))
                vals = {
                    "session_id": session.id,
                    "reconciliation_key": source_key,
                    "company_id": session.company_id.id,
                    "product_state_id": state_id,
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
                }
                overrides = preserved.get(source_key, {})
                vals.update(overrides)
                vals["review_overrides"] = overrides
                # A corrected product must never retain the previous product's lot.
                if lot and vals["product_id"] != lot.product_id.id:
                    vals["lot_id"] = False
                vals_list.append(vals)
            Line.with_context(reconciliation_generated=True).create(vals_list)

    # ------------------------------------------------------------------
    # Volcado a Inventario físico
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_serial(value):
        # Import diferido: sage_expected amplía este modelo y no puede
        # cargarse antes de que exista (rompería el registro de Odoo).
        from .sage_expected import normalize_serial
        return normalize_serial(value)

    def action_assign_company_from_sage(self):
        """Use all current matches, including companies outside the active selector.

        Reading the company only with sudo avoids silently treating a hidden
        second owner as an unambiguous match. Stock writes retain normal ACLs.
        """
        Sage = self.env["rms.sage.stock.line"].sudo()
        for session in self:
            if session.state != "review":
                raise UserError("Solo se puede asignar empresa en revisión.")
            for line in session.line_ids.filtered("lot_name"):
                matches = Sage.search([
                    ("is_current", "=", True),
                    ("serial_normalized", "=", self._normalize_serial(line.lot_name)),
                    ("product_id", "=", line.product_id.id),
                ])
                companies = matches.mapped("company_id") | matches.mapped("snapshot_id.company_id")
                if len(companies) == 1:
                    line.write({"company_id": companies.id, "company_doubtful": False})
                elif len(companies) > 1:
                    line.company_doubtful = True
        return True

    def _destination_for_company(self, location, company):
        self.ensure_one()
        if company == self.company_id:
            if location.company_id and location.company_id != company:
                raise UserError("La ubicación %s no pertenece a %s." % (location.display_name, company.display_name))
            return location
        warehouses = self.env["stock.warehouse"].search([("company_id", "=", self.company_id.id)])
        source = warehouses.filtered(lambda w: self.location_id.parent_path.startswith(w.view_location_id.parent_path))
        if len(source) != 1:
            raise UserError("No se pudo identificar el almacén de la sesión.")
        suffix = re.search(r"(\d+)$", source.code or "")
        candidates = self.env["stock.warehouse"].with_company(company).search([("company_id", "=", company.id)])
        target = candidates.filtered(lambda w: suffix and re.search(r"(\d+)$", w.code or "") and
                                     int(re.search(r"(\d+)$", w.code).group(1)) == int(suffix.group(1)))
        if len(target) != 1:
            raise UserError("No existe un almacén único en %s con el número de %s." % (company.display_name, source.code))
        if location == source.lot_stock_id:
            return target.lot_stock_id
        names = []
        current = location
        while current and current != source.lot_stock_id:
            names.append(current.name)
            current = current.location_id
        if not current:
            raise UserError("La ubicación %s no está dentro del stock de %s." % (location.display_name, source.code))
        destination = target.lot_stock_id
        for name in reversed(names):
            children = self.env["stock.location"].with_company(company).search([
                ("location_id", "=", destination.id), ("name", "=", name),
                ("company_id", "in", [company.id, False]), ("usage", "=", "internal"),
            ])
            if len(children) != 1:
                raise UserError("Falta la sububicación equivalente %s en %s." % (" / ".join(reversed(names)), target.code))
            destination = children
        return destination

    def action_apply_to_inventory(self):
        """Stage counts by company; the responsible user applies the adjustment."""
        all_quants = self.env["stock.quant"]
        for session in self:
            if session.state != "review":
                raise UserError("Solo se puede volcar un recuento que está 'En revisión'.")
            lines = session.line_ids.filtered("to_apply")
            if lines.filtered(lambda line: not line.company_id or line.company_doubtful):
                raise UserError("Hay líneas sin empresa o con empresa dudosa. Revísalas antes de volcar.")
            allowed = self.env.user.company_ids
            if any(company not in allowed for company in lines.company_id):
                raise UserError("No tienes acceso a alguna empresa de las líneas del recuento.")
            for company in lines.company_id:
                Lot = self.env["stock.lot"].with_company(company)
                Quant = self.env["stock.quant"].with_company(company).with_context(inventory_mode=True)
                for line in lines.filtered(lambda line: line.company_id == company):
                    product = line.product_id.with_company(company)
                    if product.company_id and product.company_id != company:
                        raise UserError("El producto %s pertenece a otra empresa." % product.display_name)
                    location = session._destination_for_company(line.location_id, company)
                    lot = line.lot_id.with_company(company)
                    if lot and (lot.product_id != product or (lot.company_id and lot.company_id != company)):
                        lot = Lot.browse()
                    if product.tracking != "none" and line.lot_name and not lot:
                        lot = Lot.search([
                            ("product_id", "=", product.id), ("name", "=", line.lot_name),
                            ("company_id", "in", [company.id, False]),
                        ], limit=1)
                        if not lot:
                            vals = {"product_id": product.id, "name": line.lot_name, "company_id": company.id}
                            if line.product_state_id:
                                vals["product_state_id"] = line.product_state_id.id
                            lot = Lot.create(vals)
                    if product.tracking != "none" and not lot:
                        raise UserError("La línea de %s no tiene número de serie/lote: corrígela o desmárcala antes de volcar." % product.display_name)
                    if lot:
                        line.with_context(reconciliation_generated=True).lot_id = lot
                        if line.product_state_id and lot.product_state_id != line.product_state_id:
                            lot.product_state_id = line.product_state_id
                    if product.tracking == "serial" and line.counted_qty > 0:
                        root = session._destination_for_company(session.location_id, company)
                        others = Quant.search([
                            ("product_id", "=", product.id), ("lot_id", "=", lot.id),
                            ("location_id", "child_of", root.id), ("location_id", "!=", location.id),
                            ("quantity", ">", 0),
                        ])
                        others.write({"inventory_quantity": 0, "inventory_quantity_set": True,
                                      "inventory_date": session.counting_date or fields.Date.context_today(session)})
                        all_quants |= others
                    quant = Quant.create({
                        "product_id": product.id, "location_id": location.id,
                        "lot_id": lot.id if lot else False, "inventory_quantity": line.counted_qty,
                    })
                    quant.write({"inventory_quantity_set": True,
                                 "inventory_date": session.counting_date or fields.Date.context_today(session)})
                    all_quants |= quant
            session.write({"state": "done", "date_done": fields.Datetime.now()})
        return {
            "type": "ir.actions.act_window", "name": "Inventario físico",
            "res_model": "stock.quant", "view_mode": "list",
            "domain": [("id", "in", all_quants.ids)],
            "context": {"inventory_mode": True},
        } if len(self) == 1 else True
