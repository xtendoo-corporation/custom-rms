# -*- coding: utf-8 -*-

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from ..models.stock_count_scan import clean_code


@tagged("post_install", "-at_install")
class TestCountSession(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)], limit=1
        )
        cls.stock = cls.warehouse.lot_stock_id
        cls.shelf_a = cls.env["stock.location"].create({
            "name": "Estantería A", "location_id": cls.stock.id, "barcode": "LOC-RMS-A",
        })
        cls.shelf_b = cls.env["stock.location"].create({
            "name": "Estantería B", "location_id": cls.stock.id, "barcode": "LOC-RMS-B",
        })
        Product = cls.env["product.product"]
        cls.console = Product.create({
            "name": "Consola de prueba", "is_storable": True, "tracking": "serial",
            "barcode": "RMSTEST-EAN-CONS", "default_code": "CONS-1",
        })
        cls.mic = Product.create({
            "name": "Micro de prueba", "is_storable": True, "tracking": "serial",
            "default_code": "MIC-1",
        })
        cls.cable = Product.create({
            "name": "Cable de prueba", "is_storable": True, "tracking": "none",
            "barcode": "RMSTEST-EAN-CABLE",
        })
        Lot = cls.env["stock.lot"]
        cls.lot_c1 = Lot.create({"name": "C-0001", "product_id": cls.console.id})
        cls.lot_c2 = Lot.create({"name": "C-0002", "product_id": cls.console.id})
        cls.lot_c3 = Lot.create({"name": "C-0003", "product_id": cls.console.id})
        Quant = cls.env["stock.quant"]
        Quant._update_available_quantity(cls.console, cls.shelf_a, 1, lot_id=cls.lot_c1)
        Quant._update_available_quantity(cls.console, cls.shelf_a, 1, lot_id=cls.lot_c2)
        Quant._update_available_quantity(cls.console, cls.shelf_b, 1, lot_id=cls.lot_c3)
        Quant._update_available_quantity(cls.cable, cls.shelf_a, 5)

        cls.session = cls.env["rms.stock.count.session"].create({"location_id": cls.stock.id})
        Operator = cls.env["rms.stock.count.operator"]
        cls.ana = Operator.browse(Operator.scanner_join(cls.session.id, "Ana")["operator"]["id"])
        cls.luis = Operator.browse(Operator.scanner_join(cls.session.id, "Luis")["operator"]["id"])

    def scan(self, operator, code, uid=False):
        return self.env["rms.stock.count.scan"].scanner_register(operator.id, code, uid)

    def line(self, product, lot_name=False):
        return self.session.line_ids.filtered(
            lambda l: l.product_id == product and (l.lot_name or False) == lot_name
        )

    def test_clean_code(self):
        self.assertEqual(clean_code("S/N: AB123"), "AB123")
        self.assertEqual(clean_code("SN AB123"), "AB123")
        self.assertEqual(clean_code("Serial No. 99"), "99")
        self.assertEqual(clean_code("SN12345"), "SN12345")
        self.assertEqual(clean_code("]C1ABC\x1d"), "ABC")

    def test_join_starts_session_and_reuses_operator(self):
        self.assertEqual(self.session.state, "counting")
        again = self.env["rms.stock.count.operator"].scanner_join(self.session.id, "Ana")
        self.assertEqual(again["operator"]["id"], self.ana.id)
        self.assertEqual(len(self.session.operator_ids), 2)

    def test_classification(self):
        res = self.scan(self.ana, "LOC-RMS-B")
        self.assertEqual(res["status"], "location")
        self.assertEqual(self.ana.current_location_id, self.shelf_b)

        res = self.scan(self.ana, "C-0003")
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["scan"]["type"], "serial")
        self.assertEqual(self.ana.current_product_id, self.console)

        # Nº de serie desconocido con producto actual con seguimiento: nuevo.
        res = self.scan(self.ana, "S/N: C-0099")
        self.assertEqual(res["scan"]["type"], "serial")
        self.assertTrue(res["scan"]["is_new_lot"])
        self.assertEqual(res["scan"]["lot_name"], "C-0099")

        # Código del producto con nº de serie: solo fija el producto.
        res = self.scan(self.ana, "MIC-1")
        self.assertEqual(res["status"], "product_ref")
        self.assertEqual(self.ana.current_product_id, self.mic)

        # Producto sin seguimiento: cuenta una unidad por lectura.
        res = self.scan(self.ana, "RMSTEST-EAN-CABLE")
        self.assertEqual(res["scan"]["type"], "product")

        self.ana.current_product_id = False
        res = self.scan(self.ana, "00:11:22:33:44:55")
        self.assertEqual(res["status"], "unknown")

    def test_duplicate_and_resend(self):
        self.assertEqual(self.scan(self.ana, "C-0001", "uid-1")["status"], "ok")
        # Reenvío de la misma lectura tras un corte: no se duplica.
        self.assertEqual(self.scan(self.ana, "C-0001", "uid-1")["status"], "resent")
        # Misma lectura de nuevo por el mismo operario: duplicada.
        self.assertEqual(self.scan(self.ana, "C-0001", "uid-2")["status"], "duplicate")
        # El otro operario sí puede leerlo (es lo que se cruza).
        self.assertEqual(self.scan(self.luis, "C-0001", "uid-3")["status"], "ok")
        counted = self.session.scan_ids.filtered(lambda s: s.scan_type == "serial")
        self.assertEqual(len(counted), 2)

    def test_reconciliation(self):
        # Ana: A con C-0001, C-0002 y 5 cables; nº de serie nuevo C-0099.
        self.scan(self.ana, "LOC-RMS-A")
        self.scan(self.ana, "C-0001")
        self.scan(self.ana, "C-0002")
        self.scan(self.ana, "C-0099")
        for _i in range(5):
            self.scan(self.ana, "RMSTEST-EAN-CABLE")
        # Luis: se salta C-0002 y cuenta 4 cables. Nadie ve C-0003.
        self.scan(self.luis, "LOC-RMS-A")
        self.scan(self.luis, "C-0001")
        for _i in range(4):
            self.scan(self.luis, "RMSTEST-EAN-CABLE")

        self.session.action_close_counting()
        self.assertEqual(self.session.state, "review")

        self.assertEqual(self.line(self.console, "C-0001").status, "match")
        partial = self.line(self.console, "C-0002")
        self.assertEqual(partial.status, "partial")
        self.assertEqual(partial.seen_by, "Ana")
        self.assertEqual(partial.counted_qty, 1)
        missing = self.line(self.console, "C-0003")
        self.assertEqual(missing.status, "missing")
        self.assertFalse(missing.to_apply)
        self.assertEqual(missing.location_id, self.shelf_b)
        # Nuevo, pero solo lo vio Ana: manda el desacuerdo.
        new = self.line(self.console, "C-0099")
        self.assertEqual(new.status, "partial")
        self.assertEqual(new.expected_qty, 0)
        cable = self.line(self.cable)
        self.assertEqual(cable.status, "qty_diff")
        self.assertEqual(cable.counted_qty, 5)
        self.assertEqual(cable.expected_qty, 5)

        self.assertEqual(self.session.line_missing_count, 1)
        self.assertEqual(self.session.line_partial_count, 2)

        # Volcado: C-0003 se confirma como que falta.
        missing.to_apply = True
        self.session.action_apply_to_inventory()
        self.assertEqual(self.session.state, "done")
        Quant = self.env["stock.quant"]
        q3 = Quant.search([("lot_id", "=", self.lot_c3.id), ("location_id", "=", self.shelf_b.id)])
        self.assertTrue(q3.inventory_quantity_set)
        self.assertEqual(q3.inventory_quantity, 0)
        new_lot = self.env["stock.lot"].search([
            ("product_id", "=", self.console.id), ("name", "=", "C-0099"),
        ])
        self.assertTrue(new_lot)
        q99 = Quant.search([("lot_id", "=", new_lot.id)])
        self.assertEqual(q99.location_id, self.shelf_a)
        self.assertEqual(q99.inventory_quantity, 1)
        # No se aplica el ajuste: el stock real sigue igual.
        self.assertEqual(q3.quantity, 1)

    def test_serial_found_in_other_location(self):
        self.scan(self.ana, "LOC-RMS-A")
        self.scan(self.ana, "C-0003")  # Odoo lo tiene en B
        self.scan(self.luis, "LOC-RMS-A")
        self.scan(self.luis, "C-0003")
        self.session.action_close_counting()
        line = self.line(self.console, "C-0003")
        self.assertEqual(line.status, "match")
        self.assertEqual(line.location_id, self.shelf_a)
        self.session.line_ids.filtered(lambda l: l.status == "missing").to_apply = False
        self.session.action_apply_to_inventory()
        Quant = self.env["stock.quant"]
        old = Quant.search([("lot_id", "=", self.lot_c3.id), ("location_id", "=", self.shelf_b.id)])
        new = Quant.search([("lot_id", "=", self.lot_c3.id), ("location_id", "=", self.shelf_a.id)])
        self.assertEqual(old.inventory_quantity, 0)
        self.assertTrue(old.inventory_quantity_set)
        self.assertEqual(new.inventory_quantity, 1)

    def test_assign_unknown_in_review(self):
        self.scan(self.ana, "XYZ-777")
        self.scan(self.luis, "XYZ-777")
        self.session.action_close_counting()
        self.assertEqual(self.session.unknown_count, 2)
        unknown = self.session.unknown_scan_ids
        unknown.write({"product_id": self.mic.id})
        unknown.action_assign_product()
        self.assertEqual(self.session.unknown_count, 0)
        line = self.line(self.mic, "XYZ-777")
        self.assertEqual(line.status, "unexpected")
        self.assertEqual(line.operator_seen_count, 2)

    def test_closed_session_rejects_scans(self):
        self.session.action_close_counting()
        with self.assertRaises(UserError):
            self.scan(self.ana, "C-0001")
        self.session.action_reopen()
        self.assertEqual(self.scan(self.ana, "C-0001")["status"], "ok")
