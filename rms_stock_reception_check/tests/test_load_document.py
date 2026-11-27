# -*- coding: utf-8 -*-
import base64
import io

from odoo.exceptions import UserError
from odoo.tests.common import tagged

from . import fixtures
from .common import ReceptionCommon


def _pdf(text):
    """PDF con texto de verdad (reportlab), para probar la extracción."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    for page in text.split("\x0c"):
        y = 800
        for line in page.split("\n"):
            pdf.drawString(30, y, line)
            y -= 14
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def _blank_pdf():
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    pdf.rect(50, 50, 200, 200, fill=1)
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


@tagged("post_install", "-at_install")
class TestLoadDocument(ReceptionCommon):

    def setUp(self):
        super().setUp()
        self.reception = self._reception()

    def _wizard(self, **vals):
        return self.env["rms.reception.load.wizard"].with_user(self.operator).create(
            dict({"reception_id": self.reception.id}, **vals))

    def test_pdf_meyer_preview_then_confirm(self):
        wizard = self._wizard(
            source="pdf", file=base64.b64encode(_pdf(fixtures.MEYER)), filename="invoice.pdf")
        wizard.action_read()
        self.assertEqual(wizard.step, "preview")
        self.assertEqual(wizard.detected_format, "Meyer Sound")
        self.assertEqual(len(wizard.line_ids), 6)
        # Nada guardado todavía
        self.assertFalse(self.reception.line_ids)
        ultra = wizard.line_ids.filtered(lambda l: l.supplier_code == "09.338.001.04")
        # 09.338.001.04 del proveedor = 0933800104 en Odoo
        self.assertEqual(ultra.mapped("product_id"), self.ultra)
        self.assertEqual(set(ultra.mapped("match")), {"odoo"})
        self.assertEqual(ultra.mapped("serial"), ["26470001", "26470002", "26470003"])
        self.assertEqual(ultra[0].description, "1800-LFC,EU,OT,NO RIG,GEN-1")
        self.assertFalse(any(ultra.mapped("warning")))
        # Cantidad 3 en la factura pero solo 2 series impresas: avisa, no inventa
        rig = wizard.line_ids.filtered(lambda l: l.supplier_code == "09.338.001.03")
        self.assertEqual(rig.mapped("serial"), ["26470011", "26470012"])
        self.assertIn("3 unidades", rig[0].warning)
        self.assertFalse(rig.product_id)
        frame = wizard.line_ids.filtered(lambda l: l.supplier_code == "40.338.200.01")
        self.assertEqual((frame.qty, frame.serial or "", frame.description), (4.0, "", "MCF-T2 CASTER FRAME"))
        self.assertEqual(wizard.unassigned_count, 3)
        # La vista previa se puede corregir antes de confirmar
        ultra[2].serial = "26476699"
        frame.product_id = self.bracket.id
        wizard.action_confirm()
        lines = self.reception.line_ids
        self.assertEqual(len(lines), 6)
        self.assertIn("26476699", lines.mapped("serial"))
        self.assertNotIn("26470003", lines.mapped("serial"))
        qty_line = lines.filtered(lambda l: l.product_id == self.bracket)
        self.assertTrue(qty_line.by_quantity)
        self.assertEqual(qty_line.qty_expected, 4)
        self.assertEqual(set(lines.mapped("product_state_id")), {self.state_new})
        self.assertEqual(self.reception.count_expected, 9)

    def test_scanned_pdf_is_explained(self):
        wizard = self._wizard(source="pdf", file=base64.b64encode(_blank_pdf()), filename="scan.pdf")
        with self.assertRaises(UserError) as error:
            wizard.action_read()
        self.assertIn("no tiene texto", str(error.exception))
        self.assertIn("Pegar texto", str(error.exception))
        with self.assertRaises(UserError):
            self._wizard(source="pdf", file=base64.b64encode(b"esto no es un pdf"), filename="x.pdf").action_read()

    def test_pdf_other_formats_through_wizard(self):
        for text, label, count in ((fixtures.DIGICO, "DiGiCo", 4),
                                   (fixtures.LUMINEX, "Luminex / factura hecha con Odoo", 5),
                                   (fixtures.HARVEY, "DSPecialists / Harvey", 7),
                                   (fixtures.WAVES, "Waves", 1)):
            wizard = self._wizard(source="pdf", file=base64.b64encode(_pdf(text)), filename="doc.pdf")
            wizard.action_read()
            self.assertEqual(wizard.detected_format, label)
            self.assertEqual(len(wizard.line_ids), count, label)
        wizard = self._wizard(source="pdf", file=base64.b64encode(_pdf(fixtures.DIGICO)), filename="doc.pdf")
        wizard.action_read()
        self.assertEqual(wizard.line_ids.filtered(lambda l: l.supplier_code == "X-A-168").mapped("product_id"), self.rack)

    def test_pdf_without_serials_or_text_never_invents_lines(self):
        # Factura con texto pero sin nada reconocible: se dice, no se inventa
        for text in fixtures.NO_SERIALS:
            wizard = self._wizard(source="pdf", file=base64.b64encode(_pdf(text)), filename="doc.pdf")
            with self.assertRaises(UserError) as error:
                wizard.action_read()
            self.assertIn("No he encontrado", str(error.exception))
            self.assertFalse(wizard.line_ids)
        # PDF con un solo carácter (como los escaneados reales): «no tiene texto»
        wizard = self._wizard(source="pdf", file=base64.b64encode(_pdf("\n")), filename="scan.pdf")
        with self.assertRaises(UserError) as error:
            wizard.action_read()
        self.assertIn("no tiene texto", str(error.exception))

    def test_csv_choosing_columns(self):
        content = "Referencia;Descripción;Nº de serie;Cantidad\n" \
                  "0933800104;ULTRA-X40;26476604;1\n09.338.001.04;ULTRA-X40;26476605;1\n" \
                  "4033804001;Bracket;;5\n"
        wizard = self._wizard(source="sheet", file=base64.b64encode(content.encode("utf-8")), filename="lista.csv")
        wizard.action_read()
        # Primer paso: solo se leen las columnas y se proponen
        self.assertEqual(wizard.step, "input")
        self.assertEqual(len(wizard.column_ids), 4)
        self.assertEqual(wizard.col_product_id.position, 0)
        self.assertEqual(wizard.col_serial_id.position, 2)
        self.assertEqual(wizard.col_qty_id.position, 3)
        self.assertEqual(wizard.col_description_id.position, 1)
        wizard.action_read()
        self.assertEqual(wizard.step, "preview")
        self.assertEqual(
            [(l.product_id, l.serial or "", l.qty) for l in wizard.line_ids],
            [(self.ultra, "26476604", 1.0), (self.ultra, "26476605", 1.0), (self.bracket, "", 5.0)])

    def test_xlsx_with_numeric_serials_and_custom_columns(self):
        import openpyxl

        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.append(["Bulto", "S/N", "Part"])
        sheet.append([1, 26476604, "09.338.001.04"])
        sheet.append([2, 26476605, "09.338.001.04"])
        buffer = io.BytesIO()
        workbook.save(buffer)
        wizard = self._wizard(source="sheet", file=base64.b64encode(buffer.getvalue()), filename="packing.xlsx")
        wizard.action_read()
        self.assertEqual(wizard.col_serial_id.position, 1)
        self.assertEqual(wizard.col_product_id.position, 2)
        # El usuario puede cambiar la columna elegida
        wizard.col_product_id = wizard.column_ids.filtered(lambda c: c.position == 2)
        wizard.action_read()
        self.assertEqual(wizard.line_ids.mapped("serial"), ["26476604", "26476605"])
        self.assertEqual(wizard.line_ids.mapped("product_id"), self.ultra)

    def test_paste_only_serials_and_back(self):
        wizard = self._wizard(source="paste", paste_text="26476604\n26476605\n")
        wizard.action_read()
        self.assertEqual(wizard.line_ids.mapped("serial"), ["26476604", "26476605"])
        self.assertFalse(wizard.line_ids.product_id)
        wizard.action_back()
        self.assertEqual(wizard.step, "input")
        self.assertFalse(wizard.line_ids)
        with self.assertRaises(UserError):
            self._wizard(source="paste", paste_text="  \n").action_read()

    def test_supplier_code_is_learned_when_assigned_by_hand(self):
        wizard = self._wizard(source="paste", paste_text="GX-816-EU\t25110231\nGX-816-EU\t25110232\n")
        wizard.action_read()
        self.assertFalse(wizard.line_ids.product_id)
        self.assertEqual(set(wizard.line_ids.mapped("match")), {"none"})
        # El usuario asigna el producto solo en una línea
        wizard.line_ids[0].product_id = self.galaxy.id
        wizard.action_confirm()
        self.assertEqual(self.reception.line_ids.mapped("product_id"), self.galaxy)
        learned = self.env["rms.reception.supplier.code"].search([("partner_id", "=", self.supplier.id)])
        self.assertEqual((learned.code, learned.product_id), ("GX-816-EU", self.galaxy))
        # La próxima vez sale solo (aunque venga escrito con otro formato)
        other = self._reception()
        wizard = self.env["rms.reception.load.wizard"].create({
            "reception_id": other.id, "source": "paste", "paste_text": "gx 816.eu\t25110299\n"})
        wizard.action_read()
        self.assertEqual(wizard.line_ids.product_id, self.galaxy)
        self.assertEqual(wizard.line_ids.match, "learned")
        # Otro proveedor no hereda el código
        other_supplier = self.env["res.partner"].create({"name": "Otro proveedor"})
        third = self._reception(partner_id=other_supplier.id)
        wizard = self.env["rms.reception.load.wizard"].create({
            "reception_id": third.id, "source": "paste", "paste_text": "GX-816-EU\t25110300\n"})
        wizard.action_read()
        self.assertFalse(wizard.line_ids.product_id)
        # Corregir un código ya aprendido lo actualiza, no lo duplica
        wizard = self.env["rms.reception.load.wizard"].create({
            "reception_id": other.id, "source": "paste", "paste_text": "GX-816-EU\t25110301\n"})
        wizard.action_read()
        wizard.line_ids.product_id = self.ultra.id
        wizard.action_confirm()
        learned = self.env["rms.reception.supplier.code"].search([("partner_id", "=", self.supplier.id)])
        self.assertEqual(len(learned), 1)
        self.assertEqual(learned.product_id, self.ultra)

    def test_product_lookup_normalized_and_barcode(self):
        find = self.env["rms.reception.supplier.code"]._find_product
        for code in ("0933800104", "09.338.001.04", "09 338 001 04", "0733009338015"):
            self.assertEqual(find(self.supplier, code), (self.ultra, "odoo"), code)
        self.assertEqual(find(self.supplier, "x-a 168")[0], self.rack)
        self.assertEqual(find(self.supplier, "NO-EXISTE"), (self.env["product.product"], False))
        self.assertEqual(find(self.supplier, ""), (self.env["product.product"], False))

    def test_loading_twice_does_not_duplicate_serials(self):
        text = "0933800104\t26476604\n0933800104\t26476605\n"
        for _attempt in range(2):
            wizard = self._wizard(source="paste", paste_text=text)
            wizard.action_read()
            wizard.action_confirm()
        self.assertEqual(len(self.reception.line_ids), 2)

    def test_loading_scanned_quantity_serial_reuses_line(self):
        reception = self._reception(lines=[(self.ultra, False, 2)])
        reception.action_start()
        result = self._scan(reception, "QTY-2001", product=self.ultra)
        self.assertEqual(result["verdict"], "ok")
        scanned = reception.line_ids.filtered(lambda line: line.scanned_serial == "QTY-2001")
        self.assertEqual(len(scanned), 1)
        wizard = self.env["rms.reception.load.wizard"].with_user(self.operator).create({
            "reception_id": reception.id, "source": "paste", "paste_text": "0933800104\tqty-2001\n",
        })
        wizard.action_read()
        wizard.action_confirm()
        self.assertEqual(len(reception.line_ids), 2)
        self.assertEqual(scanned.serial, "qty-2001")
        self.assertEqual(scanned.state, "received")
        self.assertEqual(reception.count_expected, 2)
        self.assertEqual(reception.count_received, 1)
        self.assertEqual(reception.count_missing, 1)

    def test_preview_replacement_fields_are_saved(self):
        wizard = self._wizard(source="paste", paste_text="0933800104\tNEW-123\n")
        wizard.action_read()
        wizard.line_ids.write({"is_replacement": True, "replaced_serials": "OLD-1, OLD-2"})
        wizard.action_confirm()
        line = self.reception.line_ids
        self.assertTrue(line.is_replacement)
        self.assertEqual(line.replaced_serials, "OLD-1, OLD-2")
