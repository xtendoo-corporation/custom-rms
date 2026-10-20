# -*- coding: utf-8 -*-

import re

from odoo import api, fields, models
from odoo.exceptions import UserError

# Prefijos que algunos fabricantes imprimen dentro del propio código de
# barras del número de serie ("S/N: 12345", "SN 12345", "SERIAL NO. 12345").
# "S/N" se quita siempre; "SN"/"SERIAL" solo si van seguidos de separador,
# para no recortar números de serie que empiezan de verdad por "SN".
_SERIAL_PREFIX_RE = re.compile(
    r"^(?:S\s*/\s*N\s*[:#.\-]?\s*|(?:SN|SERIAL(?:\s*N(?:O|UMBER)?\.?)?)\s*[:#.\-\s]\s*)",
    re.IGNORECASE,
)
# Identificador de simbología AIM (p. ej. "]C1" en GS1-128) que algunos
# lectores anteponen, y caracteres de control (separador GS de GS1).
_AIM_PREFIX_RE = re.compile(r"^\][A-Za-z][0-9A-Za-z]")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def clean_code(raw):
    code = _CONTROL_RE.sub("", raw or "").strip()
    code = _AIM_PREFIX_RE.sub("", code)
    code = _SERIAL_PREFIX_RE.sub("", code).strip()
    return code


class RmsStockCountScan(models.Model):
    """Una lectura de un operario. Se guarda en el servidor en el momento
    de escanear (no al final), así que si la PDA se bloquea, se queda sin
    batería o se recarga la página no se pierde nada."""

    _name = "rms.stock.count.scan"
    _description = "Lectura de recuento cruzado"
    _order = "scanned_at desc, id desc"
    _rec_name = "code"

    session_id = fields.Many2one(
        "rms.stock.count.session", string="Recuento", required=True, ondelete="cascade", index=True,
    )
    operator_id = fields.Many2one(
        "rms.stock.count.operator", string="Operario", required=True, ondelete="cascade", index=True,
    )
    raw_code = fields.Char(string="Lectura original", readonly=True)
    code = fields.Char(string="Código", required=True)
    scan_type = fields.Selection(
        [
            ("location", "Ubicación"),
            ("product_ref", "Producto (referencia)"),
            ("product", "Unidad de producto"),
            ("serial", "Número de serie / lote"),
            ("unknown", "Sin identificar"),
        ],
        string="Tipo", required=True,
    )
    product_id = fields.Many2one("product.product", string="Producto")
    tracking = fields.Selection(related="product_id.tracking", string="Seguimiento")
    lot_id = fields.Many2one("stock.lot", string="Nº de serie / lote en Odoo")
    lot_name = fields.Char(string="Nº de serie / lote")
    is_new_lot = fields.Boolean(
        string="Nº de serie nuevo",
        help="El número de serie no existía en Odoo: se creará al volcar el recuento.",
    )
    location_id = fields.Many2one("stock.location", string="Ubicación")
    quantity = fields.Float(string="Cantidad", default=1.0)
    scanned_at = fields.Datetime(string="Fecha", default=fields.Datetime.now, required=True)
    message = fields.Char(string="Detalle")
    ignored = fields.Boolean(
        string="Ignorar",
        help="Marcar para códigos que no son de producto (MAC, código de "
             "modelo, etiqueta de transporte...).",
    )
    client_uid = fields.Char(
        string="Id. de lectura en el dispositivo", readonly=True, index=True,
        help="Evita duplicar una lectura si la PDA la reenvía tras perder la conexión.",
    )

    # ------------------------------------------------------------------
    # Clasificación de un código escaneado
    # ------------------------------------------------------------------

    @api.model
    def _classify(self, operator, code):
        """Decide qué es el código leído, en este orden:

        1. Etiqueta de una ubicación del recuento -> cambia la ubicación.
        2. Código de barras o referencia interna de un producto:
           - sin seguimiento: cuenta 1 unidad;
           - con nº de serie/lote: solo fija el "producto actual" (la
             unidad se cuenta al leer su número de serie).
        3. Número de serie/lote que ya existe en Odoo.
        4. Si hay "producto actual" con seguimiento: número de serie NUEVO
           de ese producto.
        5. Si no, queda "sin identificar" para asignarlo en la revisión.
        """
        session = operator.session_id
        company_ids = [session.company_id.id, False]
        location = operator.current_location_id or session.location_id

        loc = self.env["stock.location"].search([
            ("barcode", "=", code),
            ("usage", "=", "internal"),
            ("company_id", "in", company_ids),
        ], limit=1)
        if loc:
            if not loc._child_of(session.location_id):
                return {
                    "scan_type": "unknown",
                    "location_id": location.id,
                    "message": "La ubicación %s no forma parte de este recuento." % loc.display_name,
                }
            return {
                "scan_type": "location",
                "location_id": loc.id,
                "message": "Ubicación: %s" % loc.display_name,
            }

        Product = self.env["product.product"]
        product = Product.search([("barcode", "=", code)], limit=1) or Product.search(
            [("default_code", "=", code)], limit=1
        )
        if product:
            if product.tracking == "none":
                return {
                    "scan_type": "product",
                    "product_id": product.id,
                    "location_id": location.id,
                    "quantity": 1.0,
                    "message": "+1 %s" % product.display_name,
                }
            return {
                "scan_type": "product_ref",
                "product_id": product.id,
                "location_id": location.id,
                "quantity": 0.0,
                "message": "Producto: %s. Escanea ahora su número de serie." % product.display_name,
            }

        lots = self.env["stock.lot"].search([
            ("name", "=", code),
            ("company_id", "in", company_ids),
        ])
        if len(lots) > 1 and operator.current_product_id:
            lots = lots.filtered(lambda l: l.product_id == operator.current_product_id) or lots
        if len(lots) == 1:
            return {
                "scan_type": "serial",
                "product_id": lots.product_id.id,
                "lot_id": lots.id,
                "lot_name": lots.name,
                "location_id": location.id,
                "quantity": 1.0,
                "message": "%s · %s" % (lots.product_id.display_name, lots.name),
            }
        if len(lots) > 1:
            return {
                "scan_type": "unknown",
                "location_id": location.id,
                "message": "El número de serie %s existe en varios productos (%s): "
                           "escanea antes el código del producto." % (
                               code, ", ".join(lots.mapped("product_id.display_name"))
                           ),
            }

        current = operator.current_product_id
        if current and current.tracking != "none":
            return {
                "scan_type": "serial",
                "product_id": current.id,
                "lot_name": code,
                "is_new_lot": True,
                "location_id": location.id,
                "quantity": 1.0,
                "message": "Nº de serie NUEVO para %s: %s" % (current.display_name, code),
            }

        return {
            "scan_type": "unknown",
            "location_id": location.id,
            "message": "Código desconocido. Elige el producto y vuelve a escanear, "
                       "o se asignará en la revisión.",
        }

    @api.model
    def scanner_register(self, operator_id, raw_code, client_uid=False):
        """Registra una lectura del escáner. Devuelve {'status', 'scan',
        'state'}; status puede ser ok | location | product_ref | unknown |
        duplicate | empty."""
        operator = self.env["rms.stock.count.operator"].browse(operator_id).exists()
        if not operator:
            raise UserError("El operario ya no existe en este recuento.")
        operator._check_counting()

        if client_uid:
            already = self.search([
                ("operator_id", "=", operator.id), ("client_uid", "=", client_uid),
            ], limit=1)
            if already:
                return {
                    "status": "resent",
                    "scan": already._scanner_payload(),
                    "state": operator._scanner_state(),
                }

        code = clean_code(raw_code)
        if not code:
            return {"status": "empty", "scan": False, "state": operator._scanner_state()}

        vals = self._classify(operator, code)

        # Un número de serie es una unidad: si ESTE operario ya lo ha
        # leído, no se vuelve a contar. Que lo lea otro operario es justo
        # lo que se busca para el cruce.
        if vals["scan_type"] == "serial":
            product = self.env["product.product"].browse(vals["product_id"])
            if product.tracking == "serial":
                previous = self.search([
                    ("operator_id", "=", operator.id),
                    ("scan_type", "=", "serial"),
                    ("product_id", "=", product.id),
                    ("lot_name", "=", vals["lot_name"]),
                    ("ignored", "=", False),
                ], limit=1)
                if previous:
                    return {
                        "status": "duplicate",
                        "scan": previous._scanner_payload(),
                        "message": "Ya habías escaneado %s." % vals["lot_name"],
                        "state": operator._scanner_state(),
                    }

        vals.update({
            "session_id": operator.session_id.id,
            "operator_id": operator.id,
            "raw_code": raw_code,
            "code": code,
            "client_uid": client_uid or False,
        })
        scan = self.create(vals)

        if scan.scan_type == "location":
            operator.current_location_id = scan.location_id
        elif scan.scan_type in ("product_ref", "product", "serial") and scan.product_id:
            operator.current_product_id = scan.product_id

        status = {
            "location": "location",
            "product_ref": "product_ref",
            "unknown": "unknown",
        }.get(scan.scan_type, "ok")
        return {
            "status": status,
            "scan": scan._scanner_payload(),
            "message": scan.message,
            "state": operator._scanner_state(),
        }

    def scanner_delete(self):
        """Borra lecturas equivocadas del propio operario mientras el
        recuento sigue abierto."""
        for scan in self:
            scan.operator_id._check_counting()
        operators = self.operator_id
        self.unlink()
        return operators[:1]._scanner_state() if len(operators) == 1 else True

    def _scanner_payload(self):
        self.ensure_one()
        return {
            "id": self.id,
            "code": self.code,
            "type": self.scan_type,
            "product_name": self.product_id.display_name or "",
            "lot_name": self.lot_name or "",
            "is_new_lot": self.is_new_lot,
            "location_name": self.location_id.display_name or "",
            "message": self.message or "",
            "time": fields.Datetime.context_timestamp(self, self.scanned_at).strftime("%H:%M:%S"),
        }

    # ------------------------------------------------------------------
    # Revisión: asignar un producto a los códigos sin identificar
    # ------------------------------------------------------------------

    def action_assign_product(self):
        """Con el producto ya rellenado a mano en la revisión, convierte la
        lectura desconocida en una lectura válida."""
        for scan in self:
            if scan.scan_type != "unknown":
                continue
            if scan.session_id.state not in ("counting", "review"):
                raise UserError("El recuento ya está cerrado.")
            product = scan.product_id
            if not product:
                raise UserError("Indica primero el producto del código %s." % scan.code)
            vals = {"quantity": 1.0, "message": "Asignado a mano a %s" % product.display_name}
            if product.tracking == "none":
                vals["scan_type"] = "product"
            else:
                lot = self.env["stock.lot"].search([
                    ("product_id", "=", product.id),
                    ("name", "=", scan.code),
                    ("company_id", "in", [scan.session_id.company_id.id, False]),
                ], limit=1)
                vals.update({
                    "scan_type": "serial",
                    "lot_id": lot.id,
                    "lot_name": scan.code,
                    "is_new_lot": not lot,
                })
            scan.write(vals)
        sessions = self.session_id.filtered(lambda s: s.state == "review")
        sessions._build_reconciliation()
        return True
