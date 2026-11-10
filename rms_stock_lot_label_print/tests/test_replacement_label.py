# -*- coding: utf-8 -*-

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestReplacementLabel(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.leopard = cls.env["product.product"].create({
            "name": "RMSTEST Meyer Leopard", "default_code": "RMSTEST-LEOPARD",
            "is_storable": True, "tracking": "serial",
        })
        cls.demo = cls.env["product.state"].search([("code", "=", "demo")], limit=1)

    def wizard(self, **vals):
        return self.env["rms.lot.label.wizard"].create(dict({"product_id": self.leopard.id}, **vals))

    def test_single_serial_needs_confirmation(self):
        wizard = self.wizard(serial_text="18175801", serial_confirm="18175810")
        with self.assertRaises(UserError):
            wizard.action_create_and_print()
        self.assertFalse(self.env["stock.lot"].search([("name", "=", "18175801")]))

    def test_engraved_serial_creates_lot_and_prints(self):
        wizard = self.wizard(
            serial_text=" 18175801 ", serial_confirm="18175801",
            reason="no_label", product_state_id=self.demo.id, copies=2,
        )
        self.assertIn("nuevo", wizard.preview)
        action = wizard.action_create_and_print()
        lot = self.env["stock.lot"].search([
            ("product_id", "=", self.leopard.id), ("name", "=", "18175801"),
        ])
        self.assertTrue(lot.rms_replacement_label)
        self.assertEqual(lot.rms_replacement_reason, "no_label")
        self.assertEqual(lot.product_state_id, self.demo)
        self.assertTrue(lot.rms_label_printed_date)
        self.assertEqual(action["type"], "ir.actions.report")
        self.assertEqual(action["data"], {"copies": 2})

        html, _type = self.env["ir.actions.report"]._render_qweb_html(
            "rms_stock_lot_label_print.action_report_lot_label_10x5", lot.ids, data={"copies": 2},
        )
        html = html.decode()
        self.assertEqual(html.count("S/N: 18175801"), 2)
        self.assertIn("RMSTEST-LEOPARD", html)
        self.assertNotIn("Etiqueta sustituta", html)
        self.assertIn(self.demo.name, html)

    def _landscape_pdf(self):
        """PDF apaisado de 50x29 mm como el que genera wkhtmltopdf."""
        import io
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(50 * mm, 29 * mm))
        c.drawString(2 * mm, 10 * mm, "ROT-1")
        c.showPage()
        c.save()
        return buf.getvalue()

    def _rendered_pages(self, report_ref):
        """Pasa un PDF apaisado por _render_qweb_pdf sin ejecutar wkhtmltopdf
        (en los tests no hay servidor web y wkhtmltopdf se queda colgado)."""
        import io
        from unittest.mock import patch
        from odoo.addons.base.models.ir_actions_report import IrActionsReport
        from odoo.tools.pdf import PdfFileReader
        with patch.object(IrActionsReport, "_render_qweb_pdf", lambda *a, **k: (self._landscape_pdf(), "pdf")):
            pdf, _type = self.env["ir.actions.report"]._render_qweb_pdf(report_ref, [1])
        reader = PdfFileReader(io.BytesIO(pdf), strict=False)
        return [reader.getPage(i) for i in range(reader.getNumPages())]

    def test_pdf_page_is_rotated_portrait(self):
        """La etiqueta sale girada: vertical 29 x 50 mm para la cinta de 29 mm."""
        pages = self._rendered_pages("rms_stock_lot_label_print.action_report_lot_label_10x5")
        self.assertEqual(len(pages), 1)
        self.assertEqual(int(pages[0].get("/Rotate", 0)) % 360, 90)
        box = pages[0].mediabox
        # Contenido apaisado 50x29; girado 90 grados se ve vertical 29x50.
        self.assertAlmostEqual(float(box.width) / 72 * 25.4, 50, delta=1)
        self.assertAlmostEqual(float(box.height) / 72 * 25.4, 29, delta=1)

    def test_other_reports_are_not_rotated(self):
        pages = self._rendered_pages("stock.action_report_delivery")
        self.assertEqual(int(pages[0].get("/Rotate", 0)) % 360, 0)

    def test_box_with_several_serials_reuses_existing(self):
        existing = self.env["stock.lot"].create({"product_id": self.leopard.id, "name": "A-1"})
        wizard = self.wizard(serial_text="A-1\nA-2\n\nA-2\nA-3", reason="multi")
        self.assertEqual(wizard.serial_count, 3)
        self.assertIn("ya existe", wizard.preview)
        wizard.action_create_and_print()
        lots = self.env["stock.lot"].search([("product_id", "=", self.leopard.id)])
        self.assertEqual(sorted(lots.mapped("name")), ["A-1", "A-2", "A-3"])
        self.assertIn(existing, lots)
        self.assertTrue(all(lots.mapped("rms_replacement_label")))

    def test_untracked_product_rejected(self):
        cable = self.env["product.product"].create({"name": "RMSTEST cable", "is_storable": True})
        wizard = self.env["rms.lot.label.wizard"].create({
            "product_id": cable.id, "serial_text": "X1", "serial_confirm": "X1",
        })
        with self.assertRaises(UserError):
            wizard.action_create_and_print()
