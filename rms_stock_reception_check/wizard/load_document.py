# -*- coding: utf-8 -*-
import base64
import csv
import io
import re

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.rms_stock_count_session.models.scan_rule import normalize_code

from ..lib import supplier_parsers
from ..models.reception_line import serial_key

_OTHER_WAYS = (
    "Otras formas de cargar la lista:\n"
    "· pide al proveedor el Excel o CSV y cárgalo con «Excel / CSV»;\n"
    "· copia las líneas del documento y pégalas con «Pegar texto»;\n"
    "· o recibe «a ciegas» (lee todas las cajas) y carga la lista cuando la tengas."
)
_HEADER_HINTS = {
    "product": ("ref", "part", "artic", "codigo", "código", "code", "sku", "producto", "product", "item", "modelo"),
    "serial": ("serie", "serial", "s/n", "sn", "seriennummer"),
    "qty": ("cant", "qty", "quantity", "unid", "uds", "menge", "units"),
    "description": ("descrip", "concepto", "bezeichnung", "nombre", "name"),
}


def extract_pdf_text(data):
    """Texto de un PDF (todas las páginas). Cadena vacía si es un escaneado."""
    from odoo.tools.pdf import PdfReader  # noqa: PLC0415 (pypdf/PyPDF2 que trae Odoo)

    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if getattr(reader, "is_encrypted", False):
            try:
                reader.decrypt("")
            except Exception:  # noqa: BLE001
                raise UserError(
                    "El PDF está protegido con contraseña y no se puede leer.\n\n" + _OTHER_WAYS) from None
        pages = []
        for page in reader.pages:
            extract = getattr(page, "extract_text", None) or getattr(page, "extractText")
            pages.append(extract() or "")
    except UserError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise UserError(
            "No se ha podido abrir el PDF (%s).\n\n%s" % (str(exc)[:120], _OTHER_WAYS)) from exc
    return "\n\x0c".join(pages)


class RmsReceptionLoadWizard(models.TransientModel):
    _name = "rms.reception.load.wizard"
    _description = "Cargar documento del proveedor"

    reception_id = fields.Many2one("rms.reception", string="Recepción", required=True, ondelete="cascade")
    partner_id = fields.Many2one(related="reception_id.partner_id", string="Proveedor")
    step = fields.Selection([("input", "Documento"), ("preview", "Vista previa")], default="input", required=True)
    source = fields.Selection(
        [("pdf", "PDF del proveedor"), ("sheet", "Excel / CSV"), ("paste", "Pegar texto")],
        string="¿Cómo llega la lista?", default="pdf", required=True,
    )
    file = fields.Binary(string="Archivo", attachment=False)
    filename = fields.Char()
    pdf_format = fields.Selection(
        [("auto", "Detectar automáticamente")] + supplier_parsers.FORMATS,
        string="Formato del documento", default="auto", required=True,
    )
    detected_format = fields.Char(string="Lector usado", readonly=True)
    paste_text = fields.Text(
        string="Texto",
        help="Una serie por línea, o «referencia <tabulador> serie». Una tercera columna es la "
             "cantidad (para lo que va sin número de serie).",
    )
    has_header = fields.Boolean(string="La primera fila son los títulos", default=True)
    column_ids = fields.One2many("rms.reception.load.column", "wizard_id", string="Columnas del archivo")
    col_product_id = fields.Many2one(
        "rms.reception.load.column", string="Columna de la referencia", domain="[('wizard_id', '=', id)]")
    col_serial_id = fields.Many2one(
        "rms.reception.load.column", string="Columna del nº de serie", domain="[('wizard_id', '=', id)]")
    col_qty_id = fields.Many2one(
        "rms.reception.load.column", string="Columna de la cantidad", domain="[('wizard_id', '=', id)]")
    col_description_id = fields.Many2one(
        "rms.reception.load.column", string="Columna de la descripción", domain="[('wizard_id', '=', id)]")
    product_state_id = fields.Many2one(
        "product.state", string="Estado de los equipos",
        compute="_compute_product_state_id", store=True, readonly=False,
    )
    line_ids = fields.One2many("rms.reception.load.line", "wizard_id", string="Vista previa")
    line_count = fields.Integer(compute="_compute_summary")
    unassigned_count = fields.Integer(compute="_compute_summary")
    summary = fields.Char(compute="_compute_summary")

    @api.depends("reception_id")
    def _compute_product_state_id(self):
        for wizard in self:
            wizard.product_state_id = wizard.reception_id.default_product_state_id

    @api.depends("line_ids.product_id", "line_ids.serial", "line_ids.qty")
    def _compute_summary(self):
        for wizard in self:
            lines = wizard.line_ids
            serials = lines.filtered("serial")
            wizard.line_count = len(lines)
            wizard.unassigned_count = len(lines.filtered(lambda l: not l.product_id))
            wizard.summary = "%d con nº de serie · %g unidades por cantidad · %d sin producto asignado" % (
                len(serials), sum((lines - serials).mapped("qty")), wizard.unassigned_count)

    @api.onchange("file", "source")
    def _onchange_file(self):
        self.column_ids = [(5, 0, 0)]
        self.col_product_id = self.col_serial_id = self.col_qty_id = self.col_description_id = False

    # ------------------------------------------------------------------
    def _reopen(self):
        return {
            "type": "ir.actions.act_window",
            "name": "Cargar documento del proveedor",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def _file_bytes(self):
        if not self.file:
            raise UserError("Elige primero el archivo.")
        return base64.b64decode(self.file)

    def _read_table(self):
        """Filas del Excel/CSV como listas de texto."""
        data = self._file_bytes()
        name = (self.filename or "").lower()
        if name.endswith(".xls") and not data[:2] == b"PK":
            raise UserError("El formato .xls antiguo no se admite: guárdalo como .xlsx o .csv y vuelve a cargarlo.")
        if data[:2] == b"PK" or name.endswith((".xlsx", ".xlsm")):
            import openpyxl  # noqa: PLC0415

            try:
                workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            except Exception as exc:  # noqa: BLE001
                raise UserError("No se ha podido abrir el Excel (%s)." % str(exc)[:120]) from exc
            sheet = workbook.worksheets[0]
            rows = []
            for row in sheet.iter_rows(values_only=True):
                cells = []
                for value in row:
                    if value is None:
                        cells.append("")
                    elif isinstance(value, float) and value.is_integer():
                        cells.append(str(int(value)))
                    else:
                        cells.append(str(value).strip())
                rows.append(cells)
        else:
            try:
                text = data.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = data.decode("latin-1")
            sample = text[:4000]
            delimiter = max(";\t,|", key=sample.count)
            rows = [[cell.strip() for cell in row] for row in csv.reader(io.StringIO(text), delimiter=delimiter)]
        rows = [row for row in rows if any(row)]
        if not rows:
            raise UserError("El archivo está vacío.")
        return rows

    def _read_columns(self):
        rows = self._read_table()
        width = max(len(row) for row in rows)
        header = rows[0] if self.has_header else []
        sample = rows[1] if self.has_header and len(rows) > 1 else rows[0]
        self.column_ids.unlink()
        columns = self.env["rms.reception.load.column"].create([{
            "wizard_id": self.id,
            "position": index,
            "name": "%s: %s%s" % (
                chr(65 + index) if index < 26 else "Col %d" % (index + 1),
                (header[index] if index < len(header) else "") or "(sin título)",
                " — p. ej. «%s»" % sample[index][:25] if index < len(sample) and sample[index] else "",
            ),
            "header": header[index] if index < len(header) else "",
        } for index in range(width)])
        guesses = {}
        for column in columns:
            title = (column.header or "").lower()
            for kind in ("serial", "qty", "description", "product"):
                if kind not in guesses and any(hint in title for hint in _HEADER_HINTS[kind]):
                    guesses[kind] = column.id
                    break
        if not self.has_header or not guesses:
            if width == 1:
                guesses = {"serial": columns[0].id}
            elif not guesses:
                guesses = {"product": columns[0].id, "serial": columns[1].id}
        self.write({
            "col_product_id": guesses.get("product"), "col_serial_id": guesses.get("serial"),
            "col_qty_id": guesses.get("qty"), "col_description_id": guesses.get("description"),
        })

    def _parse_sheet(self):
        if not self.col_serial_id and not self.col_product_id:
            raise UserError("Indica al menos la columna de la referencia o la del número de serie.")
        rows = self._read_table()
        if self.has_header:
            rows = rows[1:]

        def cell(row, column):
            return row[column.position].strip() if column and column.position < len(row) else ""

        parsed = []
        for row in rows:
            code = cell(row, self.col_product_id)
            serial_text = cell(row, self.col_serial_id)
            description = cell(row, self.col_description_id)
            if not code and not serial_text and not description:
                continue
            if serial_text:
                serials = (supplier_parsers.expand_serial_list(serial_text.replace("\n", ","))
                           if re.search(r"[,;\n]", serial_text) else [serial_text])
                for serial in serials:
                    parsed.append({"code": code, "description": description, "serial": serial, "qty": 1.0,
                                   "warning": ""})
            else:
                try:
                    quantity = float((cell(row, self.col_qty_id) or "1").replace(",", "."))
                except ValueError:
                    quantity = 1.0
                if quantity > 0:
                    parsed.append({"code": code, "description": description, "serial": "", "qty": quantity,
                                   "warning": ""})
        return parsed

    def _parse_source(self):
        self.ensure_one()
        if self.source == "paste":
            if not (self.paste_text or "").strip():
                raise UserError("Pega primero el texto de la lista.")
            self.detected_format = "Texto pegado"
            return supplier_parsers.parse_pasted(self.paste_text)
        if self.source == "sheet":
            self.detected_format = "Excel / CSV"
            return self._parse_sheet()
        text = extract_pdf_text(self._file_bytes())
        if len(re.sub(r"\s+", "", text)) < 20:
            raise UserError(
                "Este PDF no tiene texto: es un escaneado (una foto del papel) y no se puede leer "
                "automáticamente.\n\n" + _OTHER_WAYS)
        used, parsed = supplier_parsers.parse_document(text, self.pdf_format)
        self.detected_format = dict(supplier_parsers.FORMATS).get(used, used)
        if not parsed:
            raise UserError(
                "No he encontrado artículos ni números de serie en este PDF. Prueba a elegir otro "
                "formato de documento.\n\n" + _OTHER_WAYS)
        return parsed

    def action_read(self):
        """Lee el documento y enseña la vista previa (nada se guarda todavía)."""
        self.ensure_one()
        if self.source == "sheet" and not self.column_ids:
            self._read_columns()
            return self._reopen()
        parsed = self._parse_source()
        if not parsed:
            raise UserError("No hay ninguna línea que cargar.\n\n" + _OTHER_WAYS)
        SupplierCode = self.env["rms.reception.supplier.code"]
        partner = self.reception_id.partner_id
        cache = {}
        vals_list = []
        seen = set()
        for index, item in enumerate(parsed):
            code = item["code"]
            if code not in cache:
                cache[code] = SupplierCode._find_product(partner, code)
            product, origin = cache[code]
            warning = item.get("warning") or ""
            key = (normalize_code(code), serial_key(item["serial"]))
            if item["serial"] and key in seen:
                warning = (warning + " Repetido en el documento.").strip()
            seen.add(key)
            vals_list.append({
                "wizard_id": self.id, "sequence": index, "supplier_code": code,
                "description": item["description"], "serial": item["serial"], "qty": item["qty"],
                "product_id": product.id, "match": origin or "none", "warning": warning,
                "product_state_id": self.product_state_id.id,
            })
        self.line_ids.unlink()
        self.env["rms.reception.load.line"].create(vals_list)
        self.step = "preview"
        return self._reopen()

    def action_back(self):
        self.ensure_one()
        self.line_ids.unlink()
        self.step = "input"
        return self._reopen()

    def action_confirm(self):
        """Guarda la lista en la recepción, aprende los códigos asignados a
        mano y cuadra lo que ya se hubiera leído «a ciegas»."""
        self.ensure_one()
        reception = self.reception_id
        if reception.state in ("done", "cancel"):
            raise UserError("La recepción ya está cerrada.")
        if not self.line_ids:
            raise UserError("No hay ninguna línea que cargar.")
        SupplierCode = self.env["rms.reception.supplier.code"]
        partner = reception.partner_id

        # Un producto asignado a mano vale para todas las líneas del mismo artículo
        def article(line):
            return normalize_code(line.supplier_code) or "d:" + (line.description or "").strip().lower()

        assigned = {}
        for line in self.line_ids.filtered("product_id"):
            assigned.setdefault(article(line), line.product_id)
        learned = 0
        for line in self.line_ids:
            if not line.product_id and article(line) in assigned and article(line) != "d:":
                line.product_id = assigned[article(line)]
        for code_key, product in assigned.items():
            if code_key.startswith("d:"):
                continue
            code = self.line_ids.filtered(lambda l: normalize_code(l.supplier_code) == code_key)[:1].supplier_code
            auto, _origin = SupplierCode._find_product(partner, code)
            if auto != product:
                SupplierCode._learn(partner, code, product)
                learned += 1

        existing = {
            (line.product_id.id, line.serial_key)
            for line in reception.line_ids if line.origin == "list" and line.serial_key
        }
        sequence = max(reception.line_ids.filtered(lambda l: l.origin == "list").mapped("sequence") or [0])
        vals_list = []
        skipped = 0
        for line in self.line_ids.sorted(lambda l: (l.sequence, l.id)):
            serial = (line.serial or "").strip()
            if serial:
                key = (line.product_id.id, serial_key(serial))
                if key in existing:
                    skipped += 1
                    continue
                existing.add(key)
            elif line.qty <= 0:
                continue
            sequence += 1
            vals_list.append({
                "reception_id": reception.id, "origin": "list", "sequence": sequence,
                "product_id": line.product_id.id, "supplier_code": line.supplier_code,
                "description": line.description, "serial": serial or False,
                "qty_expected": 1.0 if serial else line.qty,
                "product_state_id": (line.product_state_id or self.product_state_id).id,
                "state": "pending",
            })
        new_lines = self.env["rms.reception.line"].create(vals_list)
        if reception.state == "review":
            new_lines.filtered(lambda l: not l.by_quantity).write({"state": "missing"})
        reception._reconcile_extras()
        reception.line_ids._sync_qty_state()
        if self.source != "paste" and self.file:
            self.env["ir.attachment"].create({
                "name": self.filename or "documento_proveedor", "type": "binary", "datas": self.file,
                "res_model": reception._name, "res_id": reception.id,
            })
        reception.message_post(body="Lista cargada (%s): %d líneas%s%s." % (
            self.detected_format or self.source, len(new_lines),
            ", %d repetidas no cargadas" % skipped if skipped else "",
            ", %d códigos de proveedor aprendidos" % learned if learned else ""))
        return {"type": "ir.actions.act_window_close"}


class RmsReceptionLoadColumn(models.TransientModel):
    _name = "rms.reception.load.column"
    _description = "Columna del archivo del proveedor"
    _order = "position"

    wizard_id = fields.Many2one("rms.reception.load.wizard", required=True, ondelete="cascade")
    position = fields.Integer()
    name = fields.Char()
    header = fields.Char()


class RmsReceptionLoadLine(models.TransientModel):
    _name = "rms.reception.load.line"
    _description = "Línea de la vista previa del documento"
    _order = "sequence, id"

    wizard_id = fields.Many2one("rms.reception.load.wizard", required=True, ondelete="cascade")
    sequence = fields.Integer()
    supplier_code = fields.Char(string="Código del proveedor")
    description = fields.Char(string="Descripción")
    serial = fields.Char(string="Nº de serie")
    qty = fields.Float(string="Cantidad", default=1.0)
    product_id = fields.Many2one("product.product", string="Producto en Odoo")
    product_state_id = fields.Many2one("product.state", string="Estado")
    match = fields.Selection(
        [("learned", "Código aprendido"), ("odoo", "Referencia de Odoo"), ("none", "Sin asignar")],
        string="Encontrado por", default="none", readonly=True,
    )
    warning = fields.Char(string="Aviso", readonly=True)
