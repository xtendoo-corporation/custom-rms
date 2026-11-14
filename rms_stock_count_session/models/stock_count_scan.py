# -*- coding: utf-8 -*-

import base64
import binascii
import json
import re
from urllib.parse import quote

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import SQL

from .scan_rule import _gtin_check_digit, normalize_code
from .sage_expected import normalize_serial, serial_alternatives

# Estado de Odoo (product.state.code) -> estado de Sage (prefijo del artículo,
# tal como lo devuelve el veredicto). Ex-Demo no existe en Sage: siempre
# discrepa y lo decide Administración.
SAGE_STATE_BY_CODE = {'new': 'Nuevo', 'demo': 'Demo', 'second_hand': '2Mano', 'ex_demo': 'Ex-Demo'}
SAGE_STATE_LABEL = {'new': 'Nuevo', 'demo': 'Demo', 'second_hand': '2ª mano', 'ex_demo': 'Ex-Demo',
                    'discontinued': 'Desuso'}

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
_SONY_PART_RE = re.compile(r"^P-?\d{8}-?[0-9A-Z]$", re.IGNORECASE)
_SSCC_RE = re.compile(r"^(?:\(00\)|00)\d{18}$")
_CAMERA_SERIAL_RE = re.compile(r"^S\d{2}-?\d{7}", re.IGNORECASE)


def label_print_action(url, close=False):
    """Acción de cliente del escáner que imprime la etiqueta (ver print_label.js)."""
    return {"type": "ir.actions.client", "tag": "rms_print_label", "params": {"url": url, "close": close}}


def is_valid_gtin(code):
    """EAN-8, UPC-A, EAN-13 o GTIN-14 con dígito de control correcto."""
    return (bool(code) and code.isdigit() and len(code) in (8, 12, 13, 14)
            and _gtin_check_digit(code[:-1]) == code[-1])


def clean_code(raw):
    code = _CONTROL_RE.sub("", raw or "").strip()
    # Lector con teclado inglés en un ordenador en español: el "-" llega como
    # "'" (EASN0'0005). Ningún nº de serie ni referencia lleva apóstrofo.
    code = code.replace("'", "-")
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
            ("ignored", "Ignorado (no es de producto)"),
        ],
        string="Tipo", required=True,
    )
    product_id = fields.Many2one("product.product", string="Producto")
    product_state_id = fields.Many2one("product.state", string="Estado leído")
    tracking = fields.Selection(related="product_id.tracking", string="Seguimiento")
    lot_id = fields.Many2one("stock.lot", string="Nº de serie / lote en Odoo")
    lot_name = fields.Char(string="Nº de serie / lote")
    serial_normalized = fields.Char(compute="_compute_serial_normalized", store=True, index=True)

    @api.depends("lot_name", "code", "scan_type")
    def _compute_serial_normalized(self):
        for scan in self:
            scan.serial_normalized = normalize_serial(scan.lot_name or (scan.code if scan.scan_type == "unknown" and not _SONY_PART_RE.fullmatch(scan.code or "") else ""))
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

    found_in_search = fields.Boolean(readonly=True, default=False)

    source = fields.Selection([("camera", "Cámara"), ("scanner", "PDA")], default="scanner", readonly=True)
    sage_suggestion_product_id = fields.Many2one(
        "product.product",
        string="Producto sugerido por Sage",
    )
    sage_suggestion = fields.Char(
        string="Sugerencia de Sage",
    )

    def _compute_sage_suggestion(self):
        by_session = {}
        for session in self.session_id:
            serials = self.filtered(lambda s: s.session_id == session and s.scan_type == 'unknown').mapped('serial_normalized')
            lines = self.env['rms.sage.stock.line'].sudo().search(session._sage_scope_domain() + [('serial_normalized', 'in', serials)]) if serials else self.env['rms.sage.stock.line']
            lookup = {}
            for line in lines:
                lookup.setdefault(line.serial_normalized, self.env['rms.sage.stock.line'])
                lookup[line.serial_normalized] |= line
            by_session[session.id] = lookup
        for scan in self:
            scan.sage_suggestion_product_id = False
            scan.sage_suggestion = False
            if scan.scan_type != "unknown" or not scan.serial_normalized:
                continue
            serial = scan.serial_normalized
            matches = by_session[scan.session_id.id].get(serial, self.env['rms.sage.stock.line'])
            if matches and not scan.lot_name:
                scan.lot_name = scan.code
            products = matches.product_id
            if len(products) == 1:
                scan.sage_suggestion_product_id = products
            if matches:
                scan.sage_suggestion = "; ".join(dict.fromkeys(
                    "%s · Sage: %s %s" % (
                        line.product_id.display_name or line.model_code,
                        line.warehouse_code or "", line.state_hint or "",
                    ) for line in matches
                ))

    def action_use_sage_suggestion(self):
        for scan in self:
            if not scan.sage_suggestion_product_id:
                raise UserError("Sage no propone un único producto para esta lectura.")
            scan.product_id = scan.sage_suggestion_product_id
            scan.action_assign_product()
            if scan.source != "camera":
                continue
            prefix = scan.client_uid.rsplit(":", 1)[0] if scan.client_uid and ":" in scan.client_uid else False
            peers = self.search([
                ("session_id", "=", scan.session_id.id),
                ("operator_id", "=", scan.operator_id.id),
                ("source", "=", "camera"), ("scan_type", "=", "unknown"),
            ])
            for peer in peers:
                # Aprender un código identifica todas sus lecturas de la sesión.
                # Un peer anterior puede haber convertido ya esta misma fila.
                if peer.scan_type != "unknown":
                    continue
                peer_prefix = peer.client_uid.rsplit(":", 1)[0] if peer.client_uid and ":" in peer.client_uid else False
                same_frame = (prefix == peer_prefix) if prefix and peer_prefix else (
                    scan.scanned_at.replace(microsecond=0) == peer.scanned_at.replace(microsecond=0)
                )
                if same_frame and _SONY_PART_RE.fullmatch(peer.code):
                    peer.product_id = scan.product_id
                    peer.action_learn_product_code()
        return True

    # ------------------------------------------------------------------
    # Clasificación de un código escaneado
    # ------------------------------------------------------------------

    @api.model
    def _find_lots(self, candidates, company_ids):
        """Lotes/números de serie que coinciden con alguno de los candidatos.
        Si no hay coincidencia exacta se compara sin espacios (DiGiCo
        imprime "215466 2301") y, si son solo cifras, sin ceros a la
        izquierda (Auvitran imprime '001255' y su QR da 1255)."""
        Lot = self.env["stock.lot"]
        lots = Lot.search([("name", "in", candidates), ("company_id", "in", company_ids)])
        if lots:
            return lots
        compact = list({c.replace(" ", "") for c in candidates if c.replace(" ", "")})
        numeric = list({c.lstrip("0") for c in compact if c.isdigit() and c.lstrip("0")})
        query = SQL(
            "SELECT id FROM stock_lot WHERE replace(name, ' ', '') IN %s",
            tuple(compact),
        )
        if numeric:
            query = SQL(
                "%s OR (name ~ '^[0-9 ]+$' AND ltrim(replace(name, ' ', ''), '0') IN %s)",
                query, tuple(numeric),
            )
        self.env.cr.execute(query)
        ids = [row[0] for row in self.env.cr.fetchall()]
        return Lot.search([("id", "in", ids), ("company_id", "in", company_ids)])

    @api.model
    def _classify_from_sage(self, operator, serial, base, brand_note=""):
        """El nº de serie no existe aún en Odoo: se busca en la carpeta de
        Sage (las 3 empresas). Si Sage lo tiene en un único producto, la
        lectura es ese producto con un nº de serie nuevo, sin tener que leer
        antes el código del producto. Devuelve None si Sage no lo tiene."""
        key = normalize_serial(serial)
        if not key:
            return None
        Line = self.env["rms.sage.stock.line"].sudo()
        lines = Line.search([("is_current", "=", True), ("stock_kind", "=", "stock"), ("quantity", ">", 0), ("serial_normalized", "=", key)])
        if not lines:
            lines = Line.search([("is_current", "=", True), ("stock_kind", "=", "stock"), ("quantity", ">", 0),
                                 ("serial_normalized", "in", serial_alternatives(key))])
        if not lines:
            return None
        products = lines.product_id
        current = operator.current_product_id
        if current and current in products:
            # Sony repite nº de serie entre modelos: manda el producto elegido.
            products = current
        if not products:
            articles = ", ".join(sorted(set(lines.mapped("article_code"))))
            return dict(
                base, scan_type="unknown", lot_name=serial, quantity=0.0,
                message="En Sage es %s, pero ese artículo no tiene producto en Odoo: "
                        "asígnalo en Inventario Sage > Artículos sin producto." % articles,
            )
        if len(products) > 1:
            return dict(
                base, scan_type="unknown", lot_name=serial, quantity=0.0,
                message="Según Sage, el nº de serie %s es de varios productos (%s): "
                        "escanea antes el código del producto." % (
                            serial, ", ".join(products.mapped("display_name"))),
            )
        product = products
        if product.tracking == "none":
            return dict(
                base, scan_type="unknown", lot_name=serial, product_id=product.id, quantity=0.0,
                message="En Sage es %s, pero en Odoo ese producto no se sigue por nº de "
                        "serie: actívalo en el producto." % product.display_name,
            )
        return dict(
            base, scan_type="serial", product_id=product.id, lot_name=serial,
            is_new_lot=True, quantity=1.0,
            message="%s · %s (según Sage)%s" % (product.display_name, serial, brand_note),
        )

    @api.model
    def _pick_variant(self, variants, current):
        """rms_product_import crea una variante por "Estado" (Nuevo, Demo,
        2ª Mano...) con la misma referencia. Al escanear esa referencia se
        toma la variante que ya estuviera usando el operario o, si no, la de
        "Nuevo". El estado real de cada unidad va en su número de serie."""
        if current in variants:
            return current
        for variant in variants:
            names = variant.product_template_attribute_value_ids.mapped("name")
            if any(name.strip().lower() == "nuevo" for name in names):
                return variant
        return variants[:1]

    @api.model
    def _classify(self, operator, code, camera=False):
        """Decide qué es el código leído, en este orden:

        1. Etiqueta de una ubicación del recuento -> cambia la ubicación
           (antes que las reglas, para que una estantería "A1" no se tome
           por una cantidad).
        2. Reglas de 'Ignorar' (transporte, cantidades, URLs...).
        3. Producto: código de barras (EAN/UPC/ITF-14), referencia interna o
           código alternativo:
           - sin seguimiento: cuenta 1 unidad (salvo código de caja ITF-14);
           - con nº de serie/lote: solo fija el "producto actual" (la
             unidad se cuenta al leer su número de serie).
        4. Número de serie: se extrae con las reglas de marca (si alguna
           encaja) y se busca en Odoo.
        5. Si no existe y hay "producto actual" con seguimiento: número de
           serie NUEVO de ese producto.
        6. Si no, queda "sin identificar" para asignarlo en la revisión.
        """
        session = operator.session_id
        company_ids = [session.company_id.id, False]
        location = operator.current_location_id or session.location_id
        base = {"location_id": location.id}

        loc = self.env["stock.location"].search([
            ("barcode", "=", code),
            ("usage", "=", "internal"),
            ("company_id", "in", company_ids),
        ], limit=1)
        if loc:
            if not loc._child_of(session.location_id):
                return dict(
                    base, scan_type="unknown",
                    message="La ubicación %s no forma parte de este recuento." % loc.display_name,
                )
            return {
                "scan_type": "location",
                "location_id": loc.id,
                "message": "Ubicación: %s" % loc.display_name,
            }

        rule_match = self.env["rms.scan.rule"]._match(code)
        if rule_match and rule_match["action"] == "ignore":
            return dict(
                base, scan_type="ignored", ignored=True,
                message="Ignorado: %s" % rule_match["rule"].name,
            )

        product_code = bool(rule_match and rule_match["action"] == "product_code") or bool(
            camera and _SONY_PART_RE.fullmatch(code)
        )
        if not rule_match or product_code:
            products, is_case = self.env["product.product"]._rms_find_by_code(code)
            if len(products) > 1 and len(products.product_tmpl_id) == 1:
                products = self._pick_variant(products, operator.current_product_id)
            if len(products) > 1:
                return dict(
                    base, scan_type="unknown",
                    **({"_camera_product_ids": products.ids} if camera else {}),
                    message="El código %s corresponde a varios productos (%s): elige el "
                            "producto a mano." % (code, ", ".join(products.mapped("display_name"))),
                )
            if products:
                product = products
                if product.tracking == "none" and not is_case:
                    return dict(
                        base, scan_type="product", product_id=product.id, quantity=1.0,
                        message="+1 %s" % product.display_name,
                    )
                if product.tracking == "none":
                    message = ("Caja de varias unidades de %s: escanea cada unidad."
                               % product.display_name)
                elif is_case:
                    message = ("Caja de varias unidades de %s: escanea ahora todos sus "
                               "números de serie." % product.display_name)
                else:
                    message = "Producto: %s. Escanea ahora su número de serie." % product.display_name
                return dict(
                    base, scan_type="product_ref", product_id=product.id, quantity=0.0,
                    message=message,
                )

        if product_code:
            return dict(base, scan_type="unknown", quantity=0.0,
                        message="número de pieza desconocido")

        # Product-shaped camera codes must never become invented serials,
        # including malformed GTINs whose check digit is invalid.
        if camera and not rule_match and code.isdigit() and len(code) in (8, 12, 13, 14):
            return dict(base, scan_type="unknown", quantity=0.0,
                        message="código de producto desconocido")

        serial = rule_match["serial"] if rule_match else code
        brand_note = (" (%s)" % rule_match["rule"].name) if rule_match else ""
        candidates = list(dict.fromkeys([serial, code]))
        lots = self._find_lots(candidates, company_ids)
        if len(lots) > 1 and operator.current_product_id:
            lots = lots.filtered(lambda l: l.product_id == operator.current_product_id) or lots
        if len(lots) == 1:
            return dict(
                base, scan_type="serial", product_id=lots.product_id.id, lot_id=lots.id,
                lot_name=lots.name, quantity=1.0,
                message="%s · %s%s" % (lots.product_id.display_name, lots.name, brand_note),
            )
        if len(lots) > 1:
            return dict(
                base, scan_type="unknown", lot_name=serial,
                message="El número de serie %s existe en varios productos (%s): "
                        "escanea antes el código del producto." % (
                            serial, ", ".join(lots.mapped("product_id.display_name"))
                        ),
            )

        # Pistola o teclado: un único código elegido por el operario, se fía de
        # Sage. La cámara lee todo el encuadre (kits con varios nº de serie) y
        # mantiene su regla estricta: sugerencia de Sage a confirmar.
        if not camera:
            sage_result = self._classify_from_sage(operator, serial, base, brand_note)
            if sage_result:
                return sage_result

        if camera:
            return dict(base, scan_type="unknown", lot_name=serial, quantity=0.0,
                        message="sin producto en el encuadre")

        current = operator.current_product_id
        # Un UPC/EAN de producto que Odoo no conoce (p. ej. la caja de Sound
        # Devices) nunca es un nº de serie nuevo. Tras leer el nº de serie de
        # esa misma caja es solo ruido: se ignora sin dejar nada que revisar.
        if not rule_match and is_valid_gtin(code):
            if current:
                return dict(
                    base, scan_type="ignored", ignored=True, quantity=0.0,
                    message="Código de barras del producto (%s), no es un nº de serie: no cuenta." % code,
                )
            return dict(
                base, scan_type="unknown", quantity=0.0,
                message="Código de barras de producto (UPC/EAN) que Odoo no conoce: no es un nº de "
                        "serie. Escanea el nº de serie del equipo.",
            )
        if current and current.tracking != "none":
            return dict(
                base, scan_type="serial", product_id=current.id, lot_name=serial,
                is_new_lot=True, quantity=1.0,
                message="Nº de serie NUEVO para %s: %s%s" % (current.display_name, serial, brand_note),
            )

        return dict(
            base, scan_type="unknown", lot_name=serial if rule_match else False,
            message=("Nº de serie %s%s sin producto: elige el producto y vuelve a "
                     "escanear, o se asignará en la revisión." % (serial, brand_note))
            if rule_match else
            "Código desconocido. Elige el producto y vuelve a escanear, o se "
            "asignará en la revisión.",
        )

    @api.model
    def scanner_register_batch(self, operator_id, codes, client_uid_prefix=False, source=False, search_mode=None, product_state_id=None):
        """Clasifica la etiqueta completa antes de cambiar el contexto del operario.

        El índice original identifica cada lectura aunque el orden de ejecución
        cambie: un reintento conserva el mismo control de duplicados.
        """
        operator = self.env["rms.stock.count.operator"].browse(operator_id).exists()
        if not operator:
            raise UserError("El operario ya no existe en este recuento.")
        operator._check_counting()
        self = self.with_context(found_in_search=search_mode) if search_mode is not None else self
        state = operator._scanner_product_state(product_state_id) if product_state_id is not None else operator.current_state_id
        self = self.with_context(scanner_product_state_id=state.id)
        if source == "camera":
            return self._finish_sage_batch(operator, self.with_context(sage_batch=True)._scanner_register_camera_batch(operator, codes, client_uid_prefix))
        classified = []
        for index, raw_code in enumerate(codes):
            code = clean_code(raw_code)
            vals = self._classify(operator, code) if code else {"scan_type": "unknown"}
            kind = vals["scan_type"]
            serial = kind == "serial" or (
                kind == "unknown" and (vals.get("lot_name") or _CAMERA_SERIAL_RE.match(code))
            )
            classified.append((bool(serial), index, raw_code))
        results = [
            self.with_context(sage_batch=True).scanner_register(
                operator_id, raw_code,
                "%s:%s" % (client_uid_prefix, index) if client_uid_prefix else False,
            )
            for _serial, index, raw_code in sorted(classified, key=lambda item: (item[0], item[1]))
        ]

        return self._finish_sage_batch(operator, results)

    @api.model
    def _scanner_register_camera_batch(self, operator, codes, client_uid_prefix):
        # Classify the entire frame before changing the operator's context.
        readings = [
            (index, raw, self._classify(operator, clean_code(raw), camera=True))
            for index, raw in enumerate(codes) if clean_code(raw)
        ]
        product_ids = {
            vals["product_id"] for _index, _raw, vals in readings
            if vals["scan_type"] in ("product_ref", "product")
        }
        for _index, _raw, vals in readings:
            product_ids.update(vals.pop("_camera_product_ids", []))
        # Los códigos de 3-4 cifras de IDL son logísticos únicamente si el
        # encuadre aporta contexto. DiGiCo usa 6 cifras + año/mes y no se toca.
        logistics_context = bool(product_ids) or any(
            _SSCC_RE.fullmatch(clean_code(raw)) for _index, raw, _vals in readings
        )
        if logistics_context:
            for _index, raw, vals in readings:
                if re.fullmatch(r"\d{3,4}", clean_code(raw)) and vals["scan_type"] in ("unknown", "serial"):
                    vals.clear()
                    vals.update(scan_type="ignored", ignored=True, quantity=0.0,
                                message="código logístico corto del encuadre")
        candidates = {
            vals["lot_name"] for _index, _raw, vals in readings
            if vals.get("lot_name") and vals["scan_type"] in ("serial", "unknown")
        }
        product = self.env["product.product"].browse(list(product_ids))
        sage_serial = False
        if len(product_ids) == 1 and len(candidates) > 1 and product.tracking != "none":
            expected = self.env['rms.sage.stock.line'].sudo().search(
                operator.session_id._sage_scope_domain() + [('product_id', '=', product.id)])
            expected_serials = set(expected.mapped("serial_normalized")) - {False, ""}
            matching = {serial for serial in candidates if normalize_serial(serial) in expected_serials}
            if len(matching) == 1:
                sage_serial = next(iter(matching))
        for _index, _raw, vals in readings:
            vals["source"] = "camera"
            if sage_serial and vals.get("lot_name") in candidates:
                if vals["lot_name"] != sage_serial:
                    vals.update(scan_type="ignored", ignored=True, quantity=0.0,
                                message="componente del kit (número de serie de Sage: %s)" % sage_serial)
                    continue
                # Una serie ya existente de otro producto sigue pendiente.
                if vals.get("product_id") and vals["product_id"] != product.id:
                    vals.update(scan_type="unknown", quantity=0.0,
                                message="La serie de Sage existe con otro producto en Odoo")
                    continue
                if product.tracking != "none":
                    vals.update(scan_type="serial", product_id=product.id,
                                is_new_lot=not vals.get("lot_id"), quantity=1.0,
                                message="%s · %s (Sage)" % (product.display_name, sage_serial))
                    continue
            if vals["scan_type"] != "unknown" or vals.get("message") != "sin producto en el encuadre":
                continue
            if not product_ids:
                reason = "sin producto en el encuadre"
            elif len(product_ids) > 1:
                reason = "varios productos en el encuadre"
            elif len(candidates) > 1:
                reason = "Acerca a una sola etiqueta"
            elif product.tracking == "none":
                reason = "producto sin seguimiento por número de serie"
            else:
                vals.update(scan_type="serial", product_id=product.id,
                            is_new_lot=True, quantity=1.0,
                            message="%s · %s" % (product.display_name, vals["lot_name"]))
                continue
            vals["message"] = reason
        return [
            self._scanner_register(
                operator.id, raw,
                "%s:%s" % (client_uid_prefix, index) if client_uid_prefix else False,
                classification=vals,
            )
            for index, raw, vals in sorted(
                readings, key=lambda item: (item[2]["scan_type"] == "serial", item[0]),
            )
        ]

    @api.model
    def scanner_history(self, operator_id):
        """Load this operator's session history once when opening the scanner."""
        operator = self.env["rms.stock.count.operator"].browse(operator_id).exists()
        if not operator:
            raise UserError("El operario ya no existe en este recuento.")
        operator.check_access("read")
        operator.session_id.check_access("read")
        scans = self.search([
            ("operator_id", "=", operator.id),
            ("session_id", "=", operator.session_id.id),
            ("scan_type", "!=", "location"),
        ])
        verdicts = self._sage_verdict([scan.lot_name or '' for scan in scans], operator.session_id,
                                      [scan.product_id.id for scan in scans],
                                      [scan.product_state_id.code for scan in scans], operator=operator)
        payloads = [scan.with_context(sage_batch=True)._scanner_payload() for scan in scans]
        moved = scans._moved_after_labels()
        for scan, payload, verdict in zip(scans, payloads, verdicts):
            payload['sage'] = verdict
            payload['moved_after'] = moved.get(scan.id, '')
        return payloads

    def _moved_after_labels(self):
        """{lectura: 'depósito a ACME (14-11-2026)'} si Sage en vivo trae un
        movimiento de ese nº de serie desde el día en que se leyó."""
        pairs = [(scan.serial_normalized, scan.scanned_at.date()) for scan in self
                 if scan.serial_normalized and scan.scanned_at]
        latest = self.env['rms.sage.serial.move'].sudo()._latest_after(pairs)
        return {scan.id: latest[(scan.serial_normalized, scan.scanned_at.date())]._label()
                for scan in self if scan.serial_normalized and scan.scanned_at
                and (scan.serial_normalized, scan.scanned_at.date()) in latest}

    @api.model
    def scanner_camera_config(self):
        value = self.env["ir.config_parameter"].sudo().get_param(
            "rms_stock_count_session.camera_snapshots", "True",
        )
        return {"camera_snapshots": str(value).strip().lower() not in ("false", "0", "no", "off", "")}

    @api.model
    def scanner_attach_snapshot(self, scan_id, snapshot_base64):
        """Carga independiente de la lectura: el cliente puede fallar sin perderla."""
        if not self.scanner_camera_config()["camera_snapshots"]:
            return False
        scan = self.browse(scan_id).exists()
        if not scan:
            return False
        scan.ensure_one()
        scan.check_access("write")
        # La comprobación explícita conserva el aislamiento multicompañía de
        # la sesión aunque la lectura no tenga una regla propia.
        scan.session_id.check_access("read")
        if not isinstance(snapshot_base64, str) or len(snapshot_base64) > 7 * 1024 * 1024:
            raise UserError("La captura de cámara no es válida.")
        try:
            image = base64.b64decode(snapshot_base64, validate=True)
        except (ValueError, binascii.Error):
            raise UserError("La captura de cámara no es válida.") from None
        if not image.startswith(b"\xff\xd8\xff"):
            raise UserError("La captura debe ser una imagen JPEG.")
        Attachment = self.env["ir.attachment"]
        name = "camera-scan-%s.jpg" % scan.id
        existing = Attachment.search([
            ("res_model", "=", self._name), ("res_id", "=", scan.id), ("name", "=", name),
        ], limit=1)
        if existing:
            return existing.id
        return Attachment.create({
            "name": name, "type": "binary", "mimetype": "image/jpeg",
            "datas": snapshot_base64, "res_model": self._name, "res_id": scan.id,
        }).id

    def action_view_snapshots(self):
        self.ensure_one()
        self.check_access("read")
        return {
            "type": "ir.actions.act_window",
            "name": "Capturas de la lectura",
            "res_model": "ir.attachment",
            "view_mode": "kanban,list,form",
            "domain": [("res_model", "=", self._name), ("res_id", "=", self.id)],
            "context": {"create": False},
            "target": "new",
        }

    @api.model
    def scanner_register(self, operator_id, raw_code, client_uid=False, search_mode=None, product_state_id=None):
        """Registra una lectura del escáner. Devuelve {'status', 'scan',
        'state'}; status puede ser ok | location | product_ref | unknown |
        duplicate | empty."""
        target = self.with_context(found_in_search=search_mode) if search_mode is not None else self
        if product_state_id is not None:
            state = self.env["rms.stock.count.operator"]._scanner_product_state(product_state_id)
            target = target.with_context(scanner_product_state_id=state.id)
        result = target._scanner_register(operator_id, raw_code, client_uid)
        if result.get('scan') and 'sage' in result['scan']:
            result['sage'] = result['scan']['sage']
        return result

    @api.model
    def _scanner_register(self, operator_id, raw_code, client_uid=False, classification=None):
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
                    "state": operator._scanner_state() if not self.env.context.get("sage_batch") else None,
                }

        code = clean_code(raw_code)
        if not code:
            return {"status": "empty", "scan": False, "state": operator._scanner_state() if not self.env.context.get("sage_batch") else None}

        vals = dict(classification) if classification is not None else self._classify(operator, code)

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
                    ("serial_normalized", "=", normalize_serial(vals["lot_name"])),
                    ("ignored", "=", False),
                ], limit=1)
                chosen_state = self.env["product.state"].browse(
                    self.env.context.get("scanner_product_state_id", operator.current_state_id.id))
                if previous and chosen_state and previous.product_state_id != chosen_state:
                    # Ha visto el aviso, ha corregido el estado y vuelve a
                    # leerlo: se corrige la lectura en vez de ignorarla.
                    old_name = previous.product_state_id.name or "sin estado"
                    previous.write({
                        "product_state_id": chosen_state.id,
                        "message": "%s (estado corregido: %s → %s)" % (
                            previous.message or vals["lot_name"], old_name, chosen_state.name),
                    })
                    return {
                        "status": "ok",
                        "scan": previous._scanner_payload(),
                        "message": "Estado corregido a %s." % chosen_state.name,
                        "state": operator._scanner_state() if not self.env.context.get("sage_batch") else None,
                    }
                if previous:
                    return {
                        "status": "duplicate",
                        "scan": previous._scanner_payload(),
                        "message": "Ya habías escaneado %s." % vals["lot_name"],
                        "state": operator._scanner_state() if not self.env.context.get("sage_batch") else None,
                    }

        vals.update({
            "session_id": operator.session_id.id,
            "operator_id": operator.id,
            "product_state_id": self.env.context.get("scanner_product_state_id", operator.current_state_id.id),
            "raw_code": raw_code,
            "code": code,
            "client_uid": client_uid or False,
            "found_in_search": self.env.context.get("found_in_search", operator.search_mode),
        })
        scan = self.create(vals)
        if not self.env.context.get("sage_batch"):
            scan._compute_sage_suggestion()

        if scan.scan_type == "location":
            operator.current_location_id = scan.location_id
        elif scan.scan_type in ("product_ref", "product", "serial") and scan.product_id:
            operator.current_product_id = scan.product_id

        status = {
            "location": "location",
            "product_ref": "product_ref",
            "unknown": "unknown",
            "ignored": "ignored",
        }.get(scan.scan_type, "ok")
        return {
            "status": status,
            "scan": scan._scanner_payload(),
            "message": scan.message,
            "state": operator._scanner_state() if not self.env.context.get("sage_batch") else None,
        }

    def scanner_delete(self):
        """Borra lecturas equivocadas del propio operario mientras el
        recuento sigue abierto."""
        for scan in self:
            scan.operator_id._check_counting()
        operators = self.operator_id
        self.unlink()
        return operators[:1]._scanner_state() if len(operators) == 1 else True

    LABEL_REPORT = "rms_stock_lot_label_print.report_lot_label_10x5_document"

    @api.model
    def _label_url_action(self, lots, copies=1):
        """Etiqueta lista para imprimir: el escáner la carga por detrás y abre
        directamente el cuadro de impresión (rms_print_label); en el iPad, o
        si el navegador no deja, en una pestaña nueva."""
        options = json.dumps({"copies": max(int(copies or 1), 1)}, separators=(",", ":"))
        return label_print_action("/report/pdf/%s/%s?options=%s" % (
            self.LABEL_REPORT, ",".join(str(lot_id) for lot_id in lots.ids), quote(options)))

    def scanner_print_label(self, copies=1):
        """Etiqueta sustituta de una lectura ya hecha (nº de serie y producto
        conocidos): da de alta el nº de serie en Odoo si hace falta, lo enlaza
        a la lectura y devuelve la etiqueta. No crea otra lectura."""
        self.ensure_one()
        self.operator_id._check_counting()
        serial = self.lot_id.name or self.lot_name
        if self.scan_type != "serial" or not self.product_id or not serial:
            raise UserError("Solo se puede imprimir la etiqueta de un equipo con producto y nº de serie.")
        if self.product_id.tracking == "none":
            raise UserError("%s no se sigue por nº de serie: actívalo en el producto." % self.product_id.display_name)
        wizard = self.env["rms.lot.label.wizard"].create({
            "product_id": self.product_id.id,
            "serial_text": serial,
            "serial_confirm": serial,
            "reason": "no_label",
            "product_state_id": self.product_state_id.id or False,
            "copies": max(int(copies or 1), 1),
        })
        lot = wizard._get_or_create_lots([serial])
        if self.lot_id != lot:
            self.write({"lot_id": lot.id, "is_new_lot": False})
        return self._label_url_action(lot, copies)

    def scanner_change_state(self, state_id):
        """Cambia el estado de una lectura ya hecha: se escanea seguido con un
        estado y después se corrige línea a línea el que se ve físicamente."""
        self.ensure_one()
        self.operator_id._check_counting()
        state = self.env["rms.stock.count.operator"]._scanner_product_state(state_id)
        if self.product_state_id != state:
            self.write({"product_state_id": state.id})
        return self._scanner_payload()

    def _scanner_payload(self):
        self.ensure_one()
        payload = {
            "id": self.id,
            "code": self.code,
            "type": self.scan_type,
            "product_name": self.product_id.display_name or "",
            "product_state_id": self.product_state_id.id,
            "product_state_name": self.product_state_id.name or "",
            "lot_name": self.lot_name or "",
            "is_new_lot": self.is_new_lot,
            "location_name": self.location_id.display_name or "",
            "message": self.message or "",
            "suggestion_product_id": self.sage_suggestion_product_id.id,
            "suggestion": self.sage_suggestion or "",
            "found_in_search": self.found_in_search,
            "time": fields.Datetime.context_timestamp(self, self.scanned_at).strftime("%H:%M:%S"),
            "also_in": self._counted_elsewhere(),
        }

        if not self.env.context.get("sage_batch"):
            payload['sage'] = self._sage_verdict([self.lot_name or ''], self.session_id, self.product_id,
                                                 [self.product_state_id.code], operator=self.operator_id)[0]
            payload['moved_after'] = self._moved_after_labels().get(self.id, '')
        return payload

    def _counted_elsewhere(self):
        """Nombre del otro recuento (no cancelado) en el que ya se leyó esta
        misma unidad, para no contarla dos veces entre días o naves."""
        self.ensure_one()
        if self.scan_type != "serial" or not self.serial_normalized:
            return ""
        other = self.sudo().search([
            ("id", "!=", self.id),
            ("session_id", "!=", self.session_id.id),
            ("session_id.state", "!=", "cancel"),
            ("scan_type", "=", "serial"),
            ("ignored", "=", False),
            ("serial_normalized", "=", self.serial_normalized),
            ("product_id", "=", self.product_id.id),
        ], order="scanned_at, id", limit=1)
        return other.session_id.name or ""

    @api.model
    def _refresh_sage_suggestions(self, serials):
        scans = self.search([('scan_type', '=', 'unknown'), ('session_id.state', '=', 'counting'),
                             ('serial_normalized', 'in', list(serials))])
        scans._compute_sage_suggestion()

    @api.model
    def _sage_verdict(self, serials, session, product=False, states=None, operator=None):
        """Single indexed lookup; deliberately never selects quantity or cost.

        Sage locations from other companies are exposed only as this compact
        verdict, never as browsable stock records.
        """
        session.check_access('read')
        normalized = [normalize_serial(value) for value in serials]
        keys = list(set(normalized) - {''})
        keys += [alt for key in keys for alt in serial_alternatives(key)]
        matches = {}
        if keys:
            self.env['rms.sage.stock.line'].sudo().flush_model()
            self.env.cr.execute("""
                SELECT l.serial_normalized, l.sage_company_code, COALESCE(w.code, l.warehouse_code),
                       COALESCE(w.name, l.warehouse_code), CASE l.state WHEN 'demo' THEN 'Demo' WHEN '2mano' THEN '2Mano' ELSE 'Nuevo' END, l.model_code,
                       l.product_id, l.company_id, l.brand_categ_id, l.sage_warehouse_id,
                       COALESCE(l.in_deposit, FALSE), l.article_code, l.article_name, COALESCE(w.site_number, 0)
                  FROM rms_sage_stock_line l
                  LEFT JOIN rms_sage_warehouse w ON w.id = l.sage_warehouse_id
                 WHERE l.is_current AND l.stock_kind = 'stock' AND l.quantity > 0 AND l.serial_normalized <> ''
                   AND l.serial_normalized = ANY(%s)
                 ORDER BY l.id
            """, (keys,))
            for row in self.env.cr.fetchall():
                matches.setdefault(row[0], []).append(row)
        # Nave física donde se cuenta (Sevilla = 7): un equipo que Sage solo
        # tiene en otra nave (o en un almacén dudoso) sale en ámbar "wh".
        sites = set()
        if operator and session.sage_mode == 'global':
            sites = set(operator.sudo()._progress_warehouses().mapped('site_number')) - {0}
        result = []
        pid = product.id if product and not isinstance(product, list) and len(product) == 1 else False
        for index, key in enumerate(normalized):
            if isinstance(product, list):
                pid = product[index]
            rows = matches.get(key, [])
            if not rows:
                rows = [row for alt in serial_alternatives(key) for row in matches.get(alt, [])]
            if pid and any(row[6] == pid for row in rows):
                # Sony repite nº de serie entre modelos: con el producto
                # conocido solo cuentan las líneas Sage de ese producto.
                rows = [row for row in rows if row[6] == pid]
            here = any(row[1] == session.sage_company_code and row[7] == session.company_id.id
                       and row[8] in session.brand_categ_ids.ids and row[9] in session.sage_warehouse_ids.ids for row in rows)
            # Filas idénticas (mismo archivo cargado dos veces) cuentan una vez.
            rows = list({(row[1], row[2], row[4], row[5]): row for row in rows}.values())
            if session.sage_mode == 'global':
                # Checklist global: estar en Sage (cualquier empresa/almacén) es
                # verde, salvo que el estado elegido no coincida con Sage.
                chosen = SAGE_STATE_BY_CODE.get(states[index] if states else None)
                elsewhere = bool(sites and rows and rows[0][13] not in sites)
                v = ('nos' if not key else 'none' if not rows else 'dup' if len(rows) > 1
                     else 'dep' if rows[0][10] else 'wh' if elsewhere
                     else 'est' if chosen and chosen != rows[0][4] else 'ok')
            else:
                v = ('nos' if not key else 'none' if not rows else 'dup' if len(rows) > 1
                     else 'dep' if rows[0][10]
                     else 'here' if here else 'wh' if rows[0][1] == session.sage_company_code else 'co')
            result.append({'v': v, 'n': len(rows), 'h': [list(row[1:6]) for row in rows[:3]],
                           # Artículo y nombre de Sage (para ver "Sage: ..." junto al de Odoo).
                           'sa': rows[0][11] or '' if rows else '', 'sn': rows[0][12] or '' if rows else '',
                           'pm': bool(pid and any(row[6] == pid for row in rows)),
                           'st': SAGE_STATE_LABEL.get(states[index]) if states and states[index] else ''})
        return result

    @api.model
    def _finish_sage_batch(self, operator, results):
        records = self.browse([item['scan']['id'] for item in results if item.get('scan')])
        records._compute_sage_suggestion()
        for item in results:
            if item.get('scan'):
                item['scan'] = self.browse(item['scan']['id']).with_context(sage_batch=True)._scanner_payload()
        scans = [item.get('scan') for item in results]
        # One lookup for all serials; sort each result's matches against its product.
        records = [self.browse(scan["id"]) if scan else self.browse() for scan in scans]
        verdicts = self._sage_verdict([scan.get('lot_name', '') if scan else '' for scan in scans],
                                      operator.session_id, [rec.product_id.id for rec in records],
                                      [rec.product_state_id.code for rec in records], operator=operator)
        for item, verdict in zip(results, verdicts):
            item.pop('state', None)
            item['sage'] = verdict
            if item.get('scan'):
                item['scan']['sage'] = verdict
        return {'results': results, 'state': operator.with_context(sage_batch=True)._scanner_state()}

    # ------------------------------------------------------------------
    # Revisión: asignar un producto a los códigos sin identificar
    # ------------------------------------------------------------------

    def action_assign_product(self):
        """Con el producto ya rellenado a mano en la revisión, convierte la
        lectura desconocida en una unidad de ese producto (su número de
        serie, si lo lleva)."""
        for scan in self:
            scan._check_reviewable()
            if _SONY_PART_RE.fullmatch(scan.code):
                raise UserError("Este número de pieza es un código de producto; usa Es el código del producto.")
            product = scan.product_id
            vals = {"quantity": 1.0, "message": "Asignado a mano a %s" % product.display_name}
            if product.tracking == "none":
                vals["scan_type"] = "product"
            else:
                serial = scan.lot_name or scan.code
                lot = self.env["stock.lot"].search([
                    ("product_id", "=", product.id),
                    ("name", "=", serial),
                    ("company_id", "in", [scan.session_id.company_id.id, False]),
                ], limit=1)
                vals.update({
                    "scan_type": "serial",
                    "lot_id": lot.id,
                    "lot_name": serial,
                    "is_new_lot": not lot,
                })
            scan.write(vals)
        self.session_id.filtered(lambda s: s.state == "review")._build_reconciliation()
        return True

    def action_learn_product_code(self):
        """El código desconocido era una referencia del producto (part number
        de la caja, código del ERP anterior...): se guarda como código
        alternativo del producto para que la próxima vez se reconozca solo, y
        todas las lecturas de este recuento con ese mismo código pasan a ser
        de ese producto."""
        Alias = self.env["rms.product.scan.alias"]
        for scan in self:
            scan._check_reviewable()
            product = scan.product_id
            normalized = normalize_code(scan.code)
            if not Alias.search_count([
                ("product_tmpl_id", "=", product.product_tmpl_id.id),
                ("code_normalized", "=", normalized),
            ]):
                Alias.create({
                    "product_tmpl_id": product.product_tmpl_id.id,
                    "code": scan.code,
                    "note": "Aprendido en el recuento %s" % scan.session_id.name,
                })
            same = self.search([
                ("session_id", "=", scan.session_id.id),
                ("scan_type", "=", "unknown"),
                ("code", "=", scan.code),
            ])
            if product.tracking == "none":
                same.write({
                    "scan_type": "product", "product_id": product.id, "quantity": 1.0,
                    "message": "Código de %s (aprendido)" % product.display_name,
                })
            else:
                same.write({
                    "scan_type": "product_ref", "product_id": product.id, "quantity": 0.0,
                    "message": "Código de %s (aprendido)" % product.display_name,
                })
        self.session_id.filtered(lambda s: s.state == "review")._build_reconciliation()
        return True

    def _check_reviewable(self):
        self.ensure_one()
        if self.scan_type != "unknown":
            raise UserError("La lectura %s ya está identificada." % self.code)
        if self.session_id.state not in ("counting", "review"):
            raise UserError("El recuento ya está cerrado.")
        if not self.product_id:
            raise UserError("Indica primero el producto del código %s." % self.code)
