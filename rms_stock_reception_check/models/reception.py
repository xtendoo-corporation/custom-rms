# -*- coding: utf-8 -*-
import base64
import io
from collections import OrderedDict

import xlsxwriter

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from odoo.addons.rms_stock_count_session.models.stock_count_scan import clean_code, is_valid_gtin

from .reception_line import LINE_STATES, RESOLUTIONS, serial_fuzzy, serial_key

STATES = [
    ("draft", "Borrador"),
    ("receiving", "En recepción"),
    ("review", "En revisión"),
    ("done", "Hecha"),
    ("cancel", "Cancelada"),
]
_FUZZY_MIN_LENGTH = 4


class RmsReception(models.Model):
    _name = "rms.reception"
    _description = "Recepción de proveedor con lista"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"

    name = fields.Char(string="Recepción", default="Nueva", readonly=True, copy=False)
    company_id = fields.Many2one(
        "res.company", string="Empresa", required=True, default=lambda self: self.env.company, index=True,
    )
    partner_id = fields.Many2one("res.partner", string="Proveedor", required=True, tracking=True)
    warehouse_id = fields.Many2one(
        "stock.warehouse", string="Almacén", required=True,
        default=lambda self: self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1),
        domain="[('company_id', '=', company_id)]",
    )
    location_dest_id = fields.Many2one(
        "stock.location", string="Ubicación de destino", required=True,
        compute="_compute_location_dest_id", store=True, readonly=False, precompute=True,
        domain="[('usage', '=', 'internal'), ('company_id', 'in', [company_id, False])]",
    )
    supplier_ref = fields.Char(string="Documento del proveedor", help="Nº de factura o packing list.", tracking=True)
    date = fields.Date(string="Fecha", required=True, default=fields.Date.context_today)
    state = fields.Selection(STATES, string="Estado", default="draft", required=True, copy=False, tracking=True)
    default_product_state_id = fields.Many2one(
        "product.state", string="Estado de los equipos",
        default=lambda self: self.env["stock.lot"]._default_product_state_id(),
        help="Estado con el que entran los equipos de esta recepción (por defecto, Nuevo).",
    )
    note = fields.Text(string="Notas")
    line_ids = fields.One2many("rms.reception.line", "reception_id", string="Líneas")
    incident_line_ids = fields.One2many(
        "rms.reception.line", "reception_id", string="Incidencias", domain=[("is_incident", "=", True)],
    )
    scan_ids = fields.One2many("rms.reception.scan", "reception_id", string="Lecturas")
    picking_id = fields.Many2one(
        "stock.picking", string="Albarán de entrada", copy=False, check_company=True,
        domain="[('picking_type_code', '=', 'incoming'), ('company_id', '=', company_id), "
               "('partner_id', 'child_of', partner_id), '|', ('state', 'not in', ('done', 'cancel')), "
               "('id', '=', picking_id)]",
        help="Déjalo vacío para crear un albarán nuevo al dar entrada. Si ya hay uno pendiente "
             "de este proveedor (por ejemplo, de un pedido de compra), elígelo aquí.",
    )
    count_expected = fields.Float(string="Esperado", compute="_compute_counters")
    count_received = fields.Float(string="Recibido", compute="_compute_counters")
    count_missing = fields.Float(string="Falta", compute="_compute_counters")
    count_extra = fields.Float(string="Sobrante", compute="_compute_counters")
    count_review = fields.Integer(string="A revisar", compute="_compute_counters")
    count_unresolved = fields.Integer(string="Incidencias sin resolver", compute="_compute_counters")
    scan_count = fields.Integer(string="Nº de lecturas", compute="_compute_counters")

    @api.depends("warehouse_id")
    def _compute_location_dest_id(self):
        for reception in self:
            reception.location_dest_id = reception.warehouse_id.lot_stock_id

    @api.depends("line_ids.state", "line_ids.qty_received", "line_ids.qty_expected", "line_ids.resolution")
    def _compute_counters(self):
        scan_data = dict(self.env["rms.reception.scan"]._read_group(
            [("reception_id", "in", self.ids)], ["reception_id"], ["__count"])) if self.ids else {}
        for reception in self:
            counters = reception._counters()
            reception.count_expected = counters["expected"]
            reception.count_received = counters["received"]
            reception.count_missing = counters["missing"]
            reception.count_extra = counters["extra"]
            reception.count_review = counters["review"]
            reception.count_unresolved = len(reception.line_ids.filtered("has_issue"))
            reception.scan_count = scan_data.get(reception, 0)

    def _counters(self):
        self.ensure_one()
        expected = received = missing = extra = 0.0
        review = 0
        for line in self.line_ids:
            if line.origin == "scan":
                extra += line.qty_received if line.by_quantity else 1.0
                continue
            if line.by_quantity:
                expected += line.qty_expected
                received += min(line.qty_received, line.qty_expected)
                missing += max(line.qty_expected - line.qty_received, 0.0)
                extra += max(line.qty_received - line.qty_expected, 0.0)
            else:
                expected += 1
                if line.state in ("received", "damaged"):
                    received += 1
                elif line.state in ("pending", "missing"):
                    missing += 1
            if line.state in ("probable", "wrong_model", "damaged"):
                review += 1
        return {"expected": expected, "received": received, "missing": missing, "extra": extra, "review": review}

    @api.constrains("warehouse_id", "company_id", "location_dest_id")
    def _check_company_consistency(self):
        for reception in self:
            if reception.warehouse_id.company_id != reception.company_id:
                raise ValidationError("El almacén %s no es de la empresa %s." % (
                    reception.warehouse_id.display_name, reception.company_id.display_name))
            location_company = reception.location_dest_id.company_id
            if location_company and location_company != reception.company_id:
                raise ValidationError("La ubicación de destino no es de la empresa %s." % (
                    reception.company_id.display_name))

    @api.onchange("company_id")
    def _onchange_company_id(self):
        if self.warehouse_id.company_id != self.company_id:
            self.warehouse_id = self.env["stock.warehouse"].search(
                [("company_id", "=", self.company_id.id)], limit=1)
            self.picking_id = False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == "Nueva":
                vals["name"] = self.env["ir.sequence"].next_by_code("rms.reception") or "Nueva"
            if vals.get("company_id") and not vals.get("warehouse_id"):
                vals["warehouse_id"] = self.env["stock.warehouse"].search(
                    [("company_id", "=", vals["company_id"])], limit=1).id
        return super().create(vals_list)

    @api.ondelete(at_uninstall=False)
    def _unlink_only_draft(self):
        for reception in self:
            if reception.state not in ("draft", "cancel"):
                raise UserError("Solo se puede borrar una recepción en borrador o cancelada.")

    # ------------------------------------------------------------------
    # Botones del formulario
    # ------------------------------------------------------------------
    def _check_receiving(self):
        self.ensure_one()
        if self.state != "receiving":
            raise UserError(
                "La recepción %s está «%s»: ya no admite lecturas." % (
                    self.name, dict(STATES).get(self.state)))

    def _check_manager(self):
        if not self.env.user.has_group("stock.group_stock_manager"):
            raise AccessError("Esto solo lo puede hacer un responsable de Inventario.")

    def action_start(self):
        for reception in self.filtered(lambda r: r.state == "draft"):
            reception.state = "receiving"
        return True

    def action_open_checklist(self):
        self.ensure_one()
        if self.state == "cancel":
            raise UserError("La recepción está cancelada.")
        self.action_start()
        return {
            "type": "ir.actions.client",
            "tag": "rms_stock_reception_check.checklist",
            "name": self.name,
            "params": {"reception_id": self.id},
            "context": {"active_id": self.id},
        }

    def action_load_document(self):
        self.ensure_one()
        if self.state in ("done", "cancel"):
            raise UserError("La recepción ya está cerrada.")
        return {
            "type": "ir.actions.act_window",
            "name": "Cargar documento del proveedor",
            "res_model": "rms.reception.load.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_reception_id": self.id},
        }

    def action_finish(self):
        """«He terminado»: lo que no se ha leído pasa a faltar y la recepción
        queda en manos del responsable."""
        for reception in self:
            reception._check_receiving()
            reception.state = "review"
            reception.line_ids.filtered(
                lambda l: l.state == "pending" and not l.by_quantity).write({"state": "missing"})
            reception.line_ids._sync_qty_state()
            reception.message_post(body="%s ha terminado de leer. Pendiente de revisión." % self.env.user.name)
        return True

    def action_reopen(self):
        self._check_manager()
        for reception in self:
            if reception.state != "review":
                raise UserError("Solo se puede reabrir una recepción en revisión.")
            reception.state = "receiving"
            missing = reception.line_ids.filtered(lambda l: l.state == "missing")
            missing.write({"state": "pending", "resolution": False, "resolved_by": False, "resolved_at": False})
            reception.line_ids._sync_qty_state()
        return True

    def action_cancel(self):
        for reception in self:
            if reception.state == "done":
                raise UserError("La recepción ya ha entrado en stock: no se puede cancelar.")
            if reception.state == "review":
                reception._check_manager()
            reception.state = "cancel"
        return True

    def action_view_picking(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "res_model": "stock.picking", "view_mode": "form",
            "res_id": self.picking_id.id,
        }

    def action_view_scans(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": "Lecturas", "res_model": "rms.reception.scan",
            "view_mode": "list", "domain": [("reception_id", "=", self.id)],
        }

    def action_confirm_all_probable(self):
        return self.line_ids.filtered(lambda l: l.state == "probable").action_confirm_probable()

    def action_all_missing_backorder(self):
        return self.line_ids.filtered(
            lambda l: l.state == "missing" and not l.resolution).action_res_backorder()

    def action_accept_all_extra(self):
        return self.line_ids.filtered(
            lambda l: l.state == "extra" and not l.resolution).action_res_accept()

    # ------------------------------------------------------------------
    # Pantalla de checklist
    # ------------------------------------------------------------------
    def _lock(self):
        """Dos operarios a la vez: las lecturas de una misma recepción pasan
        de una en una, así la misma caja no cuenta dos veces."""
        self.env.cr.execute("SELECT id FROM rms_reception WHERE id = %s FOR UPDATE", [self.id])
        self.env.invalidate_all()

    def checklist_state(self):
        self.ensure_one()
        self.check_access("read")
        groups = OrderedDict()
        extras = []
        for line in self.line_ids.sorted(lambda l: (l.sequence, l.id)):
            payload = line._payload()
            if line.origin == "scan":
                payload["product_name"] = line.product_id.display_name or ""
                extras.append(payload)
                continue
            product = line.product_id
            key = "p%s" % product.id if product else "t%s|%s" % (line.supplier_code or "", line.description or "")
            group = groups.get(key)
            if not group:
                group = groups[key] = {
                    "key": key,
                    "product_id": product.id or False,
                    "name": product.name or line.description or line.supplier_code or "Sin producto asignado",
                    "code": product.default_code or line.supplier_code or "",
                    "tracked": bool(product and product.tracking != "none"),
                    "no_product": not product,
                    "lines": [], "total": 0.0, "done": 0.0, "review": 0,
                }
            group["lines"].append(payload)
            if line.by_quantity:
                group["total"] += line.qty_expected
                group["done"] += min(line.qty_received, line.qty_expected)
            else:
                group["total"] += 1
                group["done"] += 1 if line.state in ("received", "damaged") else 0
            if line.state in ("probable", "wrong_model", "damaged"):
                group["review"] += 1
        scans = self.env["rms.reception.scan"].search([("reception_id", "=", self.id)], limit=12)
        return {
            "reception": {
                "id": self.id,
                "name": self.name,
                "partner": self.partner_id.display_name,
                "supplier_ref": self.supplier_ref or "",
                "state": self.state,
                "state_label": dict(STATES).get(self.state),
                "company": self.company_id.name,
                "warehouse": self.warehouse_id.name,
                "blind": not groups,
            },
            "counters": self._counters(),
            "groups": list(groups.values()),
            "extras": extras,
            "scans": [scan._payload() for scan in scans],
            "can_manage": self.env.user.has_group("stock.group_stock_manager"),
            "user": self.env.user.name,
        }

    def checklist_scan(self, raw_code, product_id=False, client_uid=False, manual=False):
        """Una lectura de la pistola (o tecleada). Devuelve el veredicto y el
        estado completo de la pantalla."""
        self.ensure_one()
        self._check_receiving()
        self._lock()
        Scan = self.env["rms.reception.scan"]
        if client_uid:
            previous = Scan.search([("reception_id", "=", self.id), ("client_uid", "=", client_uid)], limit=1)
            if previous:
                return {"result": dict(previous._payload(), resent=True), "state": self.checklist_state()}
        code = clean_code(raw_code)
        if not code:
            raise UserError("Lectura vacía.")
        context_product = self.env["product.product"].browse(product_id or []).exists()
        vals = self._classify(code, context_product, manual=manual, raw=(raw_code or "").strip())
        scan = Scan.create(dict(
            vals, reception_id=self.id, raw_code=raw_code, code=code, manual=manual, client_uid=client_uid or False,
        ))
        result = scan._payload()
        result["sets_context"] = scan.verdict == "product_code" and bool(scan.product_id)
        return {"result": result, "state": self.checklist_state()}

    def _mark_line(self, line, state, serial, context_product, manual):
        vals = {
            "state": state, "scanned_serial": serial, "scanned_by": self.env.user.id,
            "scanned_at": fields.Datetime.now(), "manual_entry": manual,
        }
        if state == "wrong_model":
            vals["scanned_product_id"] = context_product.id
        elif context_product and not line.product_id:
            vals["product_id"] = context_product.id
        line.write(vals)

    def _split_probable(self, line):
        """La lectura «parecida» que ocupaba la línea pasa a ser un sobrante."""
        extra = line.create({
            "reception_id": self.id, "origin": "scan", "state": "extra",
            "product_id": (line.scanned_product_id or line.product_id).id,
            "product_state_id": line.product_state_id.id,
            "scanned_serial": line.scanned_serial, "scanned_by": line.scanned_by.id,
            "scanned_at": line.scanned_at, "qty_expected": 0.0, "qty_received": 1.0,
            "manual_entry": line.manual_entry, "sequence": 9999,
        })
        self.env["rms.reception.scan"].search([("line_id", "=", line.id), ("undone", "=", False)]).write(
            {"line_id": extra.id, "verdict": "extra", "effect": "extra"})
        line.write({
            "state": "missing" if self.state == "review" else "pending",
            "scanned_serial": False, "scanned_product_id": False, "scanned_by": False,
            "scanned_at": False, "manual_entry": False,
        })
        return extra

    def _classify(self, code, context_product, manual=False, raw=""):
        """Decide qué es lo leído. Reglas (análisis del Caso 1, sección 5):

        - VERDE solo si coinciden producto + nº de serie con una línea
          pendiente de la lista.
        - ÁMBAR si el nº de serie está en la lista con otro modelo, o si
          solo «se parece» (O/0, I/1, ceros delante, guiones): se sugiere y
          lo confirma un responsable.
        - ROJO si no está en la lista: no se rechaza, queda registrado.
        - GRIS si es un código de producto / EAN: no cuenta, pero sirve para
          decir de qué modelo es la siguiente caja.
        - Repetido: «ya leído», no suma.
        """
        self.ensure_one()
        lines = self.line_ids
        rule = None if manual else self.env["rms.scan.rule"]._match(code)
        if rule and rule["action"] == "ignore":
            return {"verdict": "ignored", "message": "No es de producto (%s): no cuenta." % rule["rule"].name}
        serial = rule["serial"] if rule and rule["action"] == "serial" else code
        # También la lectura tal cual: clean_code quita prefijos «SN-», «S/N:» que
        # en alguna lista forman parte del nº de serie.
        keys = [key for key in dict.fromkeys([serial_key(serial), serial_key(code), serial_key(raw)]) if key]

        # 1. Ya leído (por este operario o por otro)
        read = lines.filtered(lambda l: l.scanned_key and l.scanned_key in keys)[:1]
        if read:
            return {
                "verdict": "repeat", "line_id": read.id, "product_id": read.product_id.id,
                "message": "Ya leído por %s%s. No suma." % (
                    read.scanned_by.name or "otro operario",
                    " a las %s" % fields.Datetime.context_timestamp(self, read.scanned_at).strftime("%H:%M")
                    if read.scanned_at else ""),
            }

        # 2. Nº de serie de la lista (coincidencia exacta)
        exact = lines.filtered(lambda l: l.origin == "list" and l.serial_key and l.serial_key in keys)
        if exact:
            matched = next(
                (value for value in (serial, code, raw) if serial_key(value) in exact.mapped("serial_key")), serial)
            return self._classify_exact(exact, matched, context_product, manual)

        # 3. Código de producto / EAN: gris, o +1 si el producto va por cantidad
        if not manual and (not rule or rule["action"] == "product_code"):
            product, _origin = self.env["rms.reception.supplier.code"]._find_product(self.partner_id, code)
            if product:
                if product.tracking == "none":
                    return self._classify_quantity(product)
                on_list = product in lines.filtered(lambda l: l.origin == "list").product_id
                return {
                    "verdict": "product_code", "product_id": product.id,
                    "message": "Código de producto: %s. No cuenta; lee ahora su nº de serie.%s" % (
                        product.display_name, "" if on_list or not lines else " (Este modelo no está en la lista.)"),
                }
            if rule or (code.isdigit() and len(code) in (12, 13, 14) and is_valid_gtin(code)):
                return {
                    "verdict": "product_code",
                    "message": "Código de barras de producto (no es un nº de serie): no cuenta.",
                }

        # 4. Coincidencia probable: solo se sugiere
        fuzzy_keys = {serial_fuzzy(serial), serial_fuzzy(code)} - {""}
        fuzzy = lines.filtered(
            lambda l: l.origin == "list" and l.state == "pending" and not l.by_quantity
            and len(l.serial_fuzzy or "") >= _FUZZY_MIN_LENGTH and l.serial_fuzzy in fuzzy_keys)
        if context_product:
            fuzzy = fuzzy.filtered(lambda l: not l.product_id or l.product_id == context_product)
        if len(fuzzy) == 1:
            self._mark_line(fuzzy, "probable", serial, context_product, manual)
            return {
                "verdict": "probable", "effect": "line", "line_id": fuzzy.id, "product_id": fuzzy.product_id.id,
                "message": "Se parece a %s de la lista (leído %s). Lo confirmará un responsable." % (
                    fuzzy.serial, serial),
            }

        # 5. Sobrante: no está en la lista
        product = context_product
        if not product:
            lots = self.env["stock.lot"].search([
                ("name", "in", list(dict.fromkeys([serial, code]))),
                ("company_id", "in", [self.company_id.id, False]),
            ], limit=3)
            if len(lots.product_id) == 1:
                product = lots.product_id
        extra = lines.create({
            "reception_id": self.id, "origin": "scan", "state": "extra", "product_id": product.id,
            "product_state_id": self.default_product_state_id.id, "scanned_serial": serial,
            "scanned_by": self.env.user.id, "scanned_at": fields.Datetime.now(),
            "qty_expected": 0.0, "qty_received": 1.0, "manual_entry": manual, "sequence": 9999,
        })
        blind = not lines.filtered(lambda l: l.origin == "list")
        return {
            "verdict": "extra", "effect": "extra", "line_id": extra.id, "product_id": product.id,
            "message": ("Leído %s. Todavía no hay lista: se cuadrará al cargar el documento." % serial) if blind
            else ("%s NO está en la lista: queda como sobrante para que lo decida un responsable." % serial),
        }

    def _classify_exact(self, exact, serial, context_product, manual):
        pending = exact.filtered(lambda l: l.state == "pending")
        probable = exact.filtered(lambda l: l.state == "probable")
        if not pending and probable:
            # La línea estaba ocupada por una lectura «parecida»: manda la exacta.
            self._split_probable(probable[0])
            pending = probable[0]
        if not pending:
            done = exact[0]
            return {
                "verdict": "repeat", "line_id": done.id, "product_id": done.product_id.id,
                "message": "Ya leído por %s. No suma." % (done.scanned_by.name or "otro operario"),
            }
        if context_product:
            same = pending.filtered(lambda l: not l.product_id or l.product_id == context_product)
            if not same:
                line = pending[0]
                self._mark_line(line, "wrong_model", serial, context_product, manual)
                return {
                    "verdict": "wrong_model", "effect": "line", "line_id": line.id, "product_id": line.product_id.id,
                    "message": "El nº de serie %s está en la lista como %s, pero la caja es %s. "
                               "Lo revisará un responsable." % (
                                   serial, line.product_id.display_name, context_product.display_name),
                }
            pending = same
        elif len(pending.product_id) > 1:
            return {
                "verdict": "ambiguous",
                "message": "El nº de serie %s está en la lista en varios modelos (%s): lee antes el "
                           "código del producto de la caja." % (
                               serial, ", ".join(pending.product_id.mapped("display_name"))),
            }
        line = pending[0]
        self._mark_line(line, "received", serial, context_product, manual)
        name = line.product_id.display_name or line.description or line.supplier_code or ""
        return {
            "verdict": "ok", "effect": "line", "line_id": line.id, "product_id": line.product_id.id,
            "message": "%s · %s" % (name, serial) if name else serial,
        }

    def _classify_quantity(self, product):
        """Producto sin nº de serie leído por su código: suma una unidad."""
        lines = self.line_ids.filtered(lambda l: l.by_quantity and l.product_id == product)
        listed = lines.filtered(lambda l: l.origin == "list")
        if listed:
            target = listed.filtered(lambda l: l.qty_received < l.qty_expected)[:1] or listed[-1]
            quantity = target.qty_received + 1
            target._apply_qty(quantity)
            over = quantity > target.qty_expected
            return {
                "verdict": "extra" if over else "ok", "effect": "qty", "quantity": 1.0, "line_id": target.id,
                "product_id": product.id,
                "message": "%s: %g de %g%s" % (
                    product.display_name, quantity, target.qty_expected,
                    " (más de lo esperado)" if over else ""),
            }
        target = lines.filtered(lambda l: l.origin == "scan")[:1]
        if target:
            target._apply_qty(target.qty_received + 1)
        else:
            target = lines.create({
                "reception_id": self.id, "origin": "scan", "state": "extra", "product_id": product.id,
                "product_state_id": self.default_product_state_id.id, "qty_expected": 0.0, "qty_received": 1.0,
                "scanned_by": self.env.user.id, "scanned_at": fields.Datetime.now(), "sequence": 9999,
            })
        return {
            "verdict": "extra", "effect": "qty", "quantity": 1.0, "line_id": target.id, "product_id": product.id,
            "message": "%s NO está en la lista: +1 como sobrante (%g)." % (product.display_name, target.qty_received),
        }

    def checklist_undo(self, scan_id=False):
        """Deshace una lectura (por defecto, la última propia que cambió algo).
        La lectura no se borra del registro: queda marcada como deshecha."""
        self.ensure_one()
        self._check_receiving()
        self._lock()
        Scan = self.env["rms.reception.scan"]
        domain = [("reception_id", "=", self.id), ("effect", "!=", "none"), ("undone", "=", False)]
        if scan_id:
            scan = Scan.search(domain + [("id", "=", scan_id)], limit=1)
        else:
            scan = Scan.search(domain + [("user_id", "=", self.env.uid)], limit=1)
        if not scan:
            raise UserError("No hay ninguna lectura tuya que deshacer.")
        if scan.user_id != self.env.user and not self.env.user.has_group("stock.group_stock_manager"):
            raise UserError("Esa lectura es de %s: solo puede deshacerla él o un responsable." % scan.user_id.name)
        line = scan.line_id
        scan.undone = True
        if line:
            if scan.effect == "qty":
                line._apply_qty(line.qty_received - scan.quantity)
            else:
                line._clear_reading()
        return {"undone": scan.code, "state": self.checklist_state()}

    def checklist_manual_serial(self, serial, serial_confirm, product_id=False, print_label=True):
        """Botón «Sin etiqueta»: el nº de serie se escribe dos veces, cuenta
        como una lectura normal y se imprime la etiqueta sustituta."""
        self.ensure_one()
        serial = (serial or "").strip()
        if not serial:
            raise UserError("Escribe el número de serie que pone en la placa del equipo.")
        if serial != (serial_confirm or "").strip():
            raise UserError(
                "El número de serie repetido no coincide con el primero. Revisa la placa "
                "del equipo y vuelve a escribirlo.")
        response = self.checklist_scan(serial, product_id=product_id, manual=True)
        line = self.env["rms.reception.line"].browse(response["result"]["line_id"] or []).exists()
        product = line._stock_product() if line else self.env["product.product"].browse(product_id or [])
        response["print_action"] = False
        response["print_message"] = ""
        if print_label and response["result"]["verdict"] != "repeat":
            if product and product.tracking != "none":
                wizard = self.env["rms.lot.label.wizard"].create({
                    "product_id": product.id, "serial_text": serial, "serial_confirm": serial,
                    "reason": "no_label", "copies": 1,
                    "product_state_id": (line.product_state_id or self.default_product_state_id).id or False,
                })
                lot = wizard._get_or_create_lots([serial])
                response["print_action"] = self.env["rms.stock.count.scan"]._label_url_action(lot, 1)
            else:
                response["print_message"] = (
                    "Lectura guardada, pero no se puede imprimir la etiqueta: falta saber de qué "
                    "producto es o el producto no lleva nº de serie en Odoo.")
        return response

    # ------------------------------------------------------------------
    # Recepción a ciegas: cuadrar al cargar el documento
    # ------------------------------------------------------------------
    def _reconcile_extras(self):
        """Tras cargar la lista, lo que ya se había leído «a ciegas» se cuadra
        solo: exacto -> recibido; otro modelo -> ámbar; parecido -> probable."""
        Scan = self.env["rms.reception.scan"]
        for reception in self:
            extras = reception.line_ids.filtered(lambda l: l.origin == "scan" and not l.resolution)
            for extra in extras:
                pending = reception.line_ids.filtered(lambda l: l.origin == "list" and l.state == "pending")
                if extra.by_quantity:
                    target = pending.filtered(
                        lambda l: l.by_quantity and l.product_id == extra.product_id and extra.product_id)[:1]
                    if target:
                        target._apply_qty(target.qty_received + extra.qty_received)
                        Scan.search([("line_id", "=", extra.id)]).write({"line_id": target.id})
                        extra.unlink()
                    continue
                exact = pending.filtered(lambda l: l.serial_key and l.serial_key == extra.scanned_key)
                state = "received"
                target = exact.filtered(
                    lambda l: not extra.product_id or not l.product_id or l.product_id == extra.product_id)[:1]
                if not target and exact:
                    target, state = exact[:1], "wrong_model"
                if not target:
                    fuzzy_key = serial_fuzzy(extra.scanned_serial)
                    fuzzy = pending.filtered(
                        lambda l: not l.by_quantity and len(fuzzy_key) >= _FUZZY_MIN_LENGTH
                        and l.serial_fuzzy == fuzzy_key)
                    if len(fuzzy) == 1:
                        target, state = fuzzy, "probable"
                if not target:
                    continue
                vals = {
                    "state": state, "scanned_serial": extra.scanned_serial, "scanned_by": extra.scanned_by.id,
                    "scanned_at": extra.scanned_at, "manual_entry": extra.manual_entry,
                    "damage_note": extra.damage_note,
                }
                if state == "wrong_model":
                    vals["scanned_product_id"] = extra.product_id.id
                elif state == "received" and extra.damage_note:
                    vals["state"] = "damaged"
                target.write(vals)
                Scan.search([("line_id", "=", extra.id)]).write({
                    "line_id": target.id, "effect": "line",
                    "verdict": {"received": "ok"}.get(state, state),
                })
                extra.unlink()
        return True

    # ------------------------------------------------------------------
    # Dar entrada en stock
    # ------------------------------------------------------------------
    def _stock_entries(self):
        """Lo recibido y aprobado: [(línea, producto, cantidad, nº de serie)]."""
        self.ensure_one()
        entries = []
        problems = []
        for line in self.line_ids:
            quantity = line._stock_qty()
            if quantity <= 0:
                continue
            product = line._stock_product()
            label = line.display_name
            if not product:
                problems.append("«%s» no tiene producto asignado." % label)
                continue
            serial = "" if line.by_quantity else line._stock_serial()
            if product.tracking != "none" and not serial:
                problems.append(
                    "«%s» lleva nº de serie en Odoo pero la línea va por cantidad: añade los nº de "
                    "serie o déjala fuera." % label)
                continue
            if product.tracking == "none":
                serial = ""
            entries.append((line, product, quantity, serial))
        if problems:
            raise UserError("No se puede dar entrada todavía:\n- " + "\n- ".join(problems))
        return entries

    def _check_ready_for_stock(self):
        self.ensure_one()
        if self.state != "review":
            raise UserError("Primero hay que terminar la lectura («He terminado»).")
        problems = []
        probable = self.line_ids.filtered(lambda l: l.state == "probable")
        if probable:
            problems.append("%d coincidencia(s) probable(s) sin confirmar ni descartar." % len(probable))
        unresolved = self.line_ids.filtered(lambda l: l.has_issue and l.state != "probable")
        missing = unresolved.filtered(lambda l: l.state == "missing")
        if missing:
            problems.append(
                "%d faltante(s) sin decidir: «Pendiente de llegar» o «Reclamación»." % len(missing))
        others = unresolved - missing
        if others:
            problems.append(
                "%d sobrante(s), dañado(s) o modelo(s) distinto(s) sin decidir: «Aceptar» o "
                "«Dejar fuera»." % len(others))
        if problems:
            raise UserError("Quedan incidencias por resolver:\n- " + "\n- ".join(problems))

    def action_validate_stock(self):
        """«Dar entrada en stock»: crea (o usa) el albarán de entrada y lo
        valida SOLO con lo recibido y aprobado."""
        self._check_manager()
        for reception in self:
            reception = reception.with_company(reception.company_id)
            reception._check_ready_for_stock()
            entries = reception._stock_entries()
            if entries:
                reception._create_and_validate_picking(entries)
            reception.state = "done"
            reception.message_post(body=(
                "Entrada en stock hecha por %s: %s." % (
                    self.env.user.name,
                    reception.picking_id.name if entries else "no ha entrado nada")))
        return True

    def _get_picking(self):
        self.ensure_one()
        picking = self.picking_id
        if picking:
            if picking.state in ("done", "cancel"):
                raise UserError("El albarán %s ya está cerrado: elige otro o déjalo vacío." % picking.name)
            if picking.picking_type_code != "incoming" or picking.company_id != self.company_id:
                raise UserError("El albarán %s no es una entrada de %s." % (picking.name, self.company_id.name))
            if picking.partner_id.commercial_partner_id != self.partner_id.commercial_partner_id:
                raise UserError("El albarán %s no es del proveedor %s." % (picking.name, self.partner_id.name))
            return picking
        picking_type = self.warehouse_id.in_type_id
        if not picking_type:
            raise UserError("El almacén %s no tiene tipo de operación de recepción." % self.warehouse_id.name)
        source = self.partner_id.with_company(self.company_id).property_stock_supplier \
            or picking_type.default_location_src_id
        return self.env["stock.picking"].create({
            "picking_type_id": picking_type.id,
            "partner_id": self.partner_id.id,
            "location_id": source.id,
            "location_dest_id": self.location_dest_id.id,
            "origin": " · ".join(filter(None, [self.name, self.supplier_ref])),
            "company_id": self.company_id.id,
        })

    def _create_and_validate_picking(self, entries):
        self.ensure_one()
        Lot = self.env["stock.lot"]
        Move = self.env["stock.move"]
        new_picking = not self.picking_id
        picking = self._get_picking()
        destination = self.location_dest_id if new_picking else picking.location_dest_id

        by_product = OrderedDict()
        for entry in entries:
            by_product.setdefault(entry[1], []).append(entry)

        # Nº de serie repetidos dentro de la propia recepción
        seen = set()
        for _line, product, _quantity, serial in entries:
            if serial and product.tracking == "serial":
                key = (product.id, serial)
                if key in seen:
                    raise UserError("El nº de serie %s de %s está dos veces en la recepción." % (
                        serial, product.display_name))
                seen.add(key)

        open_moves = picking.move_ids.filtered(lambda m: m.state not in ("done", "cancel"))
        for product, product_entries in by_product.items():
            if not open_moves.filtered(lambda m: m.product_id == product):
                Move.create({
                    "picking_id": picking.id,
                    "product_id": product.id,
                    "product_uom": product.uom_id.id,
                    "product_uom_qty": sum(e[2] for e in product_entries),
                    "location_id": picking.location_id.id,
                    "location_dest_id": destination.id,
                    "company_id": self.company_id.id,
                    "picking_type_id": picking.picking_type_id.id,
                })
        if picking.state == "draft":
            picking.action_confirm()
        open_moves = picking.move_ids.filtered(lambda m: m.state not in ("done", "cancel"))
        open_moves.filtered(lambda m: m.state == "draft")._action_confirm(merge=False)

        used_moves = Move
        line_by_move_line = {}
        for product, product_entries in by_product.items():
            move = open_moves.filtered(lambda m: m.product_id == product)[:1]
            used_moves |= move
            open_moves.filtered(lambda m: m.product_id == product).move_line_ids.unlink()
            for line, _product, quantity, serial in product_entries:
                vals = {
                    "move_id": move.id,
                    "picking_id": picking.id,
                    "product_id": product.id,
                    "product_uom_id": product.uom_id.id,
                    "location_id": move.location_id.id,
                    "location_dest_id": destination.id,
                    "quantity": quantity,
                    "company_id": self.company_id.id,
                }
                if serial:
                    lot = Lot.search([
                        ("product_id", "=", product.id), ("name", "=", serial),
                        ("company_id", "in", [self.company_id.id, False]),
                    ], limit=1)
                    if lot and product.tracking == "serial":
                        in_stock = self.env["stock.quant"].sudo().search_count([
                            ("lot_id", "=", lot.id), ("quantity", ">", 0),
                            ("location_id.usage", "in", ("internal", "transit")),
                        ])
                        if in_stock:
                            raise UserError(
                                "El nº de serie %s de %s ya está en el stock de Odoo: no puede "
                                "entrar otra vez. Déjalo fuera o revisa el número." % (
                                    serial, product.display_name))
                    if lot:
                        vals["lot_id"] = lot.id
                    else:
                        vals["lot_name"] = serial
                    vals["product_state_id"] = (line.product_state_id or self.default_product_state_id).id
                move_line = self.env["stock.move.line"].create(vals)
                line_by_move_line[move_line.id] = line
        used_moves.write({"picked": True})
        (open_moves - used_moves).write({"picked": False})

        result = picking.with_context(skip_backorder=True, skip_sms=True).button_validate()
        if picking.state != "done":
            detail = result.get("name") if isinstance(result, dict) else ""
            raise UserError(
                "Odoo no ha podido validar el albarán %s%s. Ábrelo desde Inventario para ver qué "
                "le falta." % (picking.name or "", " (%s)" % detail if detail else ""))
        for move_line in picking.move_line_ids:
            line = line_by_move_line.get(move_line.id)
            if line and move_line.lot_id:
                line.lot_id = move_line.lot_id.id
        self.picking_id = picking.id
        return picking

    # ------------------------------------------------------------------
    # Informe para Administración
    # ------------------------------------------------------------------
    def _report_sections(self):
        """Líneas agrupadas para el informe PDF/Excel."""
        self.ensure_one()
        lines = self.line_ids.sorted(lambda l: (l.product_id.display_name or l.description or "", l.id))
        return [
            ("Recibido", lines.filtered(lambda l: l.state == "received" and l.origin == "list"
                                        and (not l.by_quantity or l.qty_received))),
            ("Falta", lines.filtered(lambda l: l.state in ("missing", "pending") and l.origin == "list")),
            ("Sobrante (no estaba en la lista)", lines.filtered(lambda l: l.origin == "scan")),
            ("Modelo distinto / coincidencia probable",
             lines.filtered(lambda l: l.state in ("wrong_model", "probable"))),
            ("Dañado", lines.filtered(lambda l: l.state == "damaged")),
        ]

    def action_export_xlsx(self):
        self.ensure_one()
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})
        bold = workbook.add_format({"bold": True})
        title = workbook.add_format({"bold": True, "font_size": 13})
        sheet = workbook.add_worksheet("Recepción")
        sheet.write(0, 0, "Recepción %s" % self.name, title)
        sheet.write(1, 0, "Proveedor: %s · Documento: %s · Fecha: %s · Empresa: %s · Estado: %s" % (
            self.partner_id.display_name, self.supplier_ref or "-", self.date, self.company_id.name,
            dict(STATES).get(self.state)))
        counters = self._counters()
        sheet.write(2, 0, "Esperado: %g · Recibido: %g · Falta: %g · Sobrante: %g · A revisar: %d" % (
            counters["expected"], counters["received"], counters["missing"], counters["extra"],
            counters["review"]))
        headers = ["Situación", "Referencia", "Producto", "Código proveedor", "Nº serie esperado", "Nº serie leído",
                   "Esperado", "Recibido", "Estado del equipo", "Decisión", "Leído por", "Leído el", "Nota"]
        row = 4
        states = dict(LINE_STATES)
        resolutions = dict(RESOLUTIONS)
        for section, lines in self._report_sections():
            sheet.write(row, 0, "%s (%d)" % (section, len(lines)), title)
            row += 1
            for col, header in enumerate(headers):
                sheet.write(row, col, header, bold)
            row += 1
            for line in lines:
                values = [
                    states.get(line.state), line.product_id.default_code or "",
                    line.product_id.name or line.description or "", line.supplier_code or "",
                    line.serial or "", line.scanned_serial or "",
                    line.qty_expected, line.qty_received if line.by_quantity else (1 if line.scanned_serial else 0),
                    line.product_state_id.name or "", resolutions.get(line.resolution, ""),
                    line.scanned_by.name or "",
                    fields.Datetime.to_string(fields.Datetime.context_timestamp(self, line.scanned_at))[:16]
                    if line.scanned_at else "",
                    line.damage_note or "",
                ]
                for col, value in enumerate(values):
                    sheet.write(row, col, value)
                row += 1
            row += 1
        sheet.set_column(0, 0, 22)
        sheet.set_column(1, 1, 16)
        sheet.set_column(2, 2, 40)
        sheet.set_column(3, 5, 20)
        sheet.set_column(6, 12, 14)
        workbook.close()
        attachment = self.env["ir.attachment"].create({
            "name": "Recepcion_%s.xlsx" % self.name.replace("/", "-"),
            "type": "binary",
            "datas": base64.b64encode(output.getvalue()),
            "res_model": self._name,
            "res_id": self.id,
            "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        })
        return {
            "type": "ir.actions.act_url",
            "url": "/web/content/%s?download=true" % attachment.id,
            "target": "self",
        }
