# -*- coding: utf-8 -*-
import re

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

from odoo.addons.rms_stock_count_session.models.sage_expected import normalize_serial

LINE_STATES = [
    ("pending", "Pendiente"),
    ("received", "Recibido"),
    ("probable", "Coincidencia probable"),
    ("wrong_model", "Modelo distinto"),
    ("missing", "Falta"),
    ("extra", "Sobrante"),
    ("damaged", "Dañado"),
]
RESOLUTIONS = [
    ("backorder", "Pendiente de llegar"),
    ("claim", "Reclamación al proveedor"),
    ("accept", "Aceptado: entra en stock"),
    ("reject", "Se deja fuera"),
]
INCIDENT_STATES = ("probable", "wrong_model", "missing", "extra", "damaged")

_FUZZY_TABLE = str.maketrans({"O": "0", "Q": "0", "I": "1", "L": "1"})


def serial_key(value):
    """Forma EXACTA de un nº de serie: solo se ignoran mayúsculas y espacios
    al principio y al final. Es la única que pone una línea en verde."""
    return (value or "").strip().upper()


def serial_fuzzy(value):
    """Forma «parecida»: sin guiones, espacios, puntos ni ceros delante y con
    O=0, I=L=1. Solo sirve para SUGERIR una coincidencia probable."""
    key = normalize_serial(value)
    if not key:
        return ""
    return key.translate(_FUZZY_TABLE).lstrip("0") or "0"


class RmsReceptionLine(models.Model):
    _name = "rms.reception.line"
    _description = "Línea de recepción de proveedor"
    _order = "reception_id, sequence, id"
    _rec_name = "display_name"

    reception_id = fields.Many2one(
        "rms.reception", string="Recepción", required=True, ondelete="cascade", index=True,
    )
    company_id = fields.Many2one(related="reception_id.company_id", store=True, index=True)
    partner_id = fields.Many2one(related="reception_id.partner_id", store=True, string="Proveedor")
    reception_state = fields.Selection(related="reception_id.state", string="Estado de la recepción", store=True)
    sequence = fields.Integer(default=10)
    origin = fields.Selection(
        [("list", "Lista del proveedor"), ("scan", "Leído sin estar en la lista")],
        string="Origen", default="list", required=True, readonly=True,
    )
    product_id = fields.Many2one("product.product", string="Producto", index=True)
    supplier_code = fields.Char(string="Código del proveedor")
    description = fields.Char(string="Descripción del documento")
    serial = fields.Char(string="Nº de serie esperado")
    serial_key = fields.Char(compute="_compute_keys", store=True, index=True)
    serial_fuzzy = fields.Char(compute="_compute_keys", store=True, index=True)
    by_quantity = fields.Boolean(
        string="Por cantidad", compute="_compute_by_quantity", store=True,
        help="La línea no trae nº de serie: se recibe contando unidades.",
    )
    qty_expected = fields.Float(string="Cantidad esperada", default=1.0)
    qty_received = fields.Float(string="Cantidad recibida", copy=False)
    product_state_id = fields.Many2one(
        "product.state", string="Estado del equipo",
        default=lambda self: self.env["stock.lot"]._default_product_state_id(),
    )
    state = fields.Selection(LINE_STATES, string="Situación", default="pending", required=True, copy=False, index=True)
    scanned_serial = fields.Char(string="Nº de serie leído", copy=False)
    scanned_key = fields.Char(compute="_compute_keys", store=True, index=True)
    scanned_product_id = fields.Many2one("product.product", string="Producto leído", copy=False)
    scanned_by = fields.Many2one("res.users", string="Leído por", copy=False, readonly=True)
    scanned_at = fields.Datetime(string="Leído el", copy=False, readonly=True)
    manual_entry = fields.Boolean(string="Escrito a mano (sin etiqueta)", copy=False, readonly=True)
    damage_note = fields.Char(string="Daño observado", copy=False)
    resolution = fields.Selection(RESOLUTIONS, string="Decisión", copy=False)
    resolved_by = fields.Many2one("res.users", string="Decidido por", copy=False, readonly=True)
    resolved_at = fields.Datetime(string="Decidido el", copy=False, readonly=True)
    is_incident = fields.Boolean(string="Es incidencia", compute="_compute_incident", store=True)
    has_issue = fields.Boolean(string="Sin resolver", compute="_compute_incident", store=True, index=True)
    lot_id = fields.Many2one("stock.lot", string="Nº de serie en Odoo", copy=False, readonly=True)

    @api.depends("serial", "scanned_serial")
    def _compute_keys(self):
        for line in self:
            line.serial_key = serial_key(line.serial)
            line.serial_fuzzy = serial_fuzzy(line.serial)
            line.scanned_key = serial_key(line.scanned_serial)

    @api.depends("serial", "scanned_serial")
    def _compute_by_quantity(self):
        for line in self:
            line.by_quantity = not (line.serial or "").strip() and not (line.scanned_serial or "").strip()

    @api.depends("state", "resolution", "by_quantity", "qty_expected", "qty_received", "reception_id.state")
    def _compute_incident(self):
        for line in self:
            over = bool(
                line.by_quantity and line.origin == "list" and line.qty_received > line.qty_expected
            )
            incident = line.state in INCIDENT_STATES or over
            line.is_incident = incident
            line.has_issue = bool(
                incident and not line.resolution and line.reception_id.state in ("receiving", "review")
            )

    @api.depends("product_id", "serial", "scanned_serial", "description", "supplier_code")
    def _compute_display_name(self):
        for line in self:
            what = line.product_id.display_name or line.description or line.supplier_code or "Sin producto"
            serial = line.scanned_serial or line.serial
            line.display_name = "%s · %s" % (what, serial) if serial else what

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("serial"):
                vals["serial"] = re.sub(r"\s+", " ", vals["serial"]).strip()
                vals.setdefault("qty_expected", 1.0)
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Lo que hace el operario
    # ------------------------------------------------------------------
    def _sync_qty_state(self):
        """Estado de una línea por cantidad según lo contado."""
        for line in self.filtered("by_quantity"):
            if line.origin != "list" or line.state == "damaged":
                continue
            if line.reception_id.state == "receiving":
                state = "received" if line.qty_expected and line.qty_received >= line.qty_expected else "pending"
            else:
                state = "received" if line.qty_received >= line.qty_expected else "missing"
            if line.state != state:
                line.state = state

    def _clear_reading(self):
        """Deja la línea como si nadie la hubiera leído."""
        list_lines = self.filtered(lambda l: l.origin == "list")
        (self - list_lines).unlink()
        list_lines.write({
            "state": "pending", "scanned_serial": False, "scanned_product_id": False,
            "scanned_by": False, "scanned_at": False, "manual_entry": False,
            "damage_note": False, "resolution": False, "resolved_by": False,
            "resolved_at": False, "qty_received": 0.0,
        })

    def checklist_unreceive(self):
        """Botón «Desmarcar» de la pantalla: quita la lectura de la línea."""
        self.ensure_one()
        reception = self.reception_id
        reception._check_receiving()
        if self.state == "pending" and not self.qty_received:
            raise UserError("Esta línea todavía no se ha leído.")
        self.env["rms.reception.scan"].search([
            ("line_id", "=", self.id), ("undone", "=", False),
        ]).write({"undone": True})
        self._clear_reading()
        return reception.checklist_state()

    def checklist_set_damaged(self, note=False, damaged=True):
        """Marca (o desmarca) la caja como dañada, con una nota."""
        self.ensure_one()
        reception = self.reception_id
        reception._check_receiving()
        if damaged:
            if self.state not in ("received", "damaged", "extra", "wrong_model"):
                raise UserError("Lee primero la caja; después márcala como dañada.")
            if not (note or "").strip():
                raise UserError("Escribe qué daño tiene la caja.")
            vals = {"damage_note": note.strip()}
            if self.state == "received":
                vals["state"] = "damaged"
            self.write(vals)
        elif self.state == "damaged":
            self.write({"state": "received", "damage_note": False, "resolution": False})
        else:
            self.write({"damage_note": False})
        return reception.checklist_state()

    def checklist_set_qty(self, quantity):
        """Líneas por cantidad: fija lo contado (botones +/− o tecleado)."""
        self.ensure_one()
        reception = self.reception_id
        reception._check_receiving()
        if not self.by_quantity:
            raise UserError("Esta línea va con número de serie: lee la caja con la pistola.")
        try:
            quantity = max(float(quantity), 0.0)
        except (TypeError, ValueError):
            raise UserError("Escribe una cantidad válida.") from None
        delta = quantity - self.qty_received
        if not delta:
            return reception.checklist_state()
        self.env["rms.reception.scan"].create({
            "reception_id": reception.id, "line_id": self.id, "code": self.product_id.default_code or "cantidad",
            "verdict": "ok", "effect": "qty", "quantity": delta, "product_id": self.product_id.id,
            "message": "%s: %g de %g" % (self.product_id.display_name or self.description or "", quantity, self.qty_expected),
        })
        self._apply_qty(quantity)
        return reception.checklist_state()

    def _apply_qty(self, quantity):
        self.ensure_one()
        if self.origin == "scan" and quantity <= 0:
            self.unlink()
            return
        self.write({
            "qty_received": quantity,
            "scanned_by": self.env.user.id if quantity else False,
            "scanned_at": fields.Datetime.now() if quantity else False,
        })
        self._sync_qty_state()

    # ------------------------------------------------------------------
    # Lo que decide el responsable
    # ------------------------------------------------------------------
    def _check_manager(self):
        if not self.env.user.has_group("stock.group_stock_manager"):
            raise AccessError("Solo un responsable de Inventario puede resolver las incidencias.")
        for line in self:
            if line.reception_id.state in ("done", "cancel"):
                raise UserError("La recepción %s ya está cerrada." % line.reception_id.name)

    def _resolve(self, resolution, allowed):
        self._check_manager()
        for line in self:
            if not line.is_incident:
                raise UserError("«%s» no es una incidencia." % line.display_name)
            if line.state == "probable":
                raise UserError(
                    "«%s» es una coincidencia probable: primero confírmala o descártala." % line.display_name)
            kind = "missing" if line.state == "missing" else "other"
            if kind not in allowed:
                raise UserError(
                    "Para un faltante se elige «Pendiente de llegar» o «Reclamación»; para sobrantes, "
                    "dañados o modelos distintos, «Aceptar» o «Dejar fuera» (%s)." % line.display_name)
        self.write({
            "resolution": resolution, "resolved_by": self.env.user.id, "resolved_at": fields.Datetime.now(),
        })
        return True

    def action_res_backorder(self):
        return self._resolve("backorder", ("missing",))

    def action_res_claim(self):
        return self._resolve("claim", ("missing",))

    def action_res_accept(self):
        return self._resolve("accept", ("other",))

    def action_res_reject(self):
        return self._resolve("reject", ("other",))

    def action_res_clear(self):
        self._check_manager()
        self.write({"resolution": False, "resolved_by": False, "resolved_at": False})
        return True

    def action_confirm_probable(self):
        """El responsable confirma que lo leído ES la línea de la lista
        (O/0, I/1, ceros delante, guiones...). Pasa a recibido."""
        self._check_manager()
        for line in self:
            if line.state != "probable":
                raise UserError("«%s» no es una coincidencia probable." % line.display_name)
        self.write({"state": "received", "resolved_by": self.env.user.id, "resolved_at": fields.Datetime.now()})
        return True

    def action_reject_probable(self):
        """No es el mismo equipo: lo leído queda como sobrante y la línea de
        la lista vuelve a estar sin recibir."""
        self._check_manager()
        for line in self:
            if line.state != "probable":
                raise UserError("«%s» no es una coincidencia probable." % line.display_name)
            line.reception_id._split_probable(line)
        return True

    # ------------------------------------------------------------------
    # Entrada en stock
    # ------------------------------------------------------------------
    def _stock_product(self):
        self.ensure_one()
        if self.state == "wrong_model" and self.scanned_product_id:
            return self.scanned_product_id
        return self.product_id

    def _stock_serial(self):
        self.ensure_one()
        return (self.scanned_serial or self.serial or "").strip()

    def _stock_qty(self):
        """Unidades de esta línea que entran en stock (0 = no entra)."""
        self.ensure_one()
        accepted = self.resolution == "accept"
        if self.by_quantity:
            if self.origin == "scan" or self.state in ("extra", "damaged", "wrong_model"):
                return self.qty_received if accepted else 0.0
            if self.qty_received > self.qty_expected and not accepted:
                return self.qty_expected
            return self.qty_received
        if self.state == "received":
            return 1.0
        if self.state in ("extra", "damaged", "wrong_model") and accepted:
            return 1.0
        return 0.0

    def _payload(self):
        self.ensure_one()
        return {
            "id": self.id,
            "product_id": self.product_id.id or False,
            "serial": self.serial or "",
            "scanned_serial": self.scanned_serial or "",
            "by_quantity": self.by_quantity,
            "qty_expected": self.qty_expected,
            "qty_received": self.qty_received,
            "state": self.state,
            "origin": self.origin,
            "state_name": self.product_state_id.name or "",
            "scanned_product": self.scanned_product_id.display_name or "",
            "user": self.scanned_by.name or "",
            "time": fields.Datetime.context_timestamp(self, self.scanned_at).strftime("%H:%M") if self.scanned_at else "",
            "damage_note": self.damage_note or "",
            "manual": self.manual_entry,
            "description": self.description or "",
            "supplier_code": self.supplier_code or "",
        }
