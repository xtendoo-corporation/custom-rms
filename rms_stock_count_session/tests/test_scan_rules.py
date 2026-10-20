# -*- coding: utf-8 -*-
"""Lecturas reales sacadas de las fotos de etiquetas del almacén."""

from odoo.tests import TransactionCase, tagged

from ..models.scan_rule import gtin_variants, normalize_code


@tagged("post_install", "-at_install")
class TestScanRules(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)], limit=1
        )
        cls.stock = warehouse.lot_stock_id
        cls.shelf = cls.env["stock.location"].create({
            "name": "Hueco A1", "location_id": cls.stock.id, "barcode": "A1",
        })
        Product = cls.env["product.product"]

        def product(name, tracking="serial", **vals):
            return Product.create(dict(
                {"name": name, "is_storable": True, "tracking": tracking}, **vals
            ))

        cls.axc_avb = product("RMSTEST AxC-AVB")
        cls.avbx7 = product("RMSTEST AVBx7/SB+r")
        cls.dwm = product("RMSTEST Sony DWM-02N")
        cls.aza = product("RMSTEST Atlas AZA404")
        cls.fc4t = product("RMSTEST Atlas FC-4T")
        cls.williams = product("RMSTEST Williams BA SYS1-01", barcode="707976006110")
        cls.gigacore = product("RMSTEST LumiNode 12", default_code="LU0100072")
        cls.neutrik = product("RMSTEST Neutrik NO2M4DW-FX", barcode="7613187014406")
        cls.s21 = product("RMSTEST DiGiCo S21")
        cls.cable = product("RMSTEST Cable", tracking="none", barcode="RMSTEST-CABLE")

        upc_fc4t = gtin_variants("10612079703163")[0][-1]
        cls.fc4t.barcode = upc_fc4t
        cls.env["rms.product.scan.alias"].create({
            "product_tmpl_id": cls.dwm.product_tmpl_id.id, "code": "P-81660762-I",
        })
        Lot = cls.env["stock.lot"]
        Lot.create({"name": "001255", "product_id": cls.axc_avb.id})
        Lot.create({"name": "00000794", "product_id": cls.avbx7.id})
        Lot.create({"name": "CV700722322000148", "product_id": cls.aza.id})

        cls.session = cls.env["rms.stock.count.session"].create({"location_id": cls.stock.id})
        Operator = cls.env["rms.stock.count.operator"]
        cls.op = Operator.browse(Operator.scanner_join(cls.session.id, "Ana")["operator"]["id"])

    def scan(self, code):
        return self.env["rms.stock.count.scan"].scanner_register(self.op.id, code)

    def test_helpers(self):
        self.assertEqual(normalize_code("LU 01 00072"), "LU0100072")
        self.assertEqual(normalize_code("09.336.001.02"), "0933600102")
        variants, is_case = gtin_variants("10612079703163")
        self.assertTrue(is_case)
        self.assertIn("0612079703166", variants)
        self.assertIn("612079703166", variants)
        self.assertEqual(gtin_variants("0707976006110"), (["0707976006110", "707976006110"], False))

    def test_ignored_codes(self):
        for code in (
            "(00)050134930120831424",  # SSCC Sony
            "00050134930120831424",
            "01",  # cantidad DiGiCo
            "https://digico.biz/recycling-information/",
            "A410001587102C0087",  # pegatina DiGiCo
            "S01-0000000-T",  # caja de kit Sony sin nº de serie
        ):
            res = self.scan(code)
            self.assertEqual(res["status"], "ignored", code)
        self.assertFalse(self.session.scan_ids.filtered(lambda s: s.scan_type in ("serial", "product", "unknown")))

    def test_short_location_barcode_wins(self):
        self.assertEqual(self.scan("A1")["status"], "location")
        self.assertEqual(self.op.current_location_id, self.shelf)

    def test_auvitran_qr(self):
        res = self.scan("FF01140004E7")
        self.assertEqual(res["scan"]["type"], "serial")
        self.assertEqual(res["scan"]["lot_name"], "001255")
        self.assertEqual(self.op.current_product_id, self.axc_avb)
        # Lote dado de alta con 8 cifras: se encuentra sin mirar los ceros.
        res = self.scan("FF01FA00031A")
        self.assertEqual(res["scan"]["lot_name"], "00000794")
        self.assertFalse(res["scan"]["is_new_lot"])
        # Nuevo: se crea con 6 cifras como en la etiqueta de las tarjetas.
        res = self.scan("FF010A000369")
        self.assertEqual(res["scan"]["lot_name"], "000873")
        self.assertTrue(res["scan"]["is_new_lot"])

    def test_sony_labels(self):
        res = self.scan("P81660762I")  # referencia Sony registrada como alias
        self.assertEqual(res["status"], "product_ref")
        self.assertEqual(self.op.current_product_id, self.dwm)
        res = self.scan("S010040579B")
        self.assertEqual(res["scan"]["type"], "serial")
        self.assertEqual(res["scan"]["lot_name"], "0040579")
        self.assertTrue(res["scan"]["is_new_lot"])

    def test_atlas_serial_prefix_and_case_code(self):
        res = self.scan("SNCV700722322000148")
        self.assertEqual(res["scan"]["lot_name"], "CV700722322000148")
        self.assertEqual(res["scan"]["product_name"], self.aza.display_name)
        # Caja de 2 FC-4T: el ITF-14 identifica el producto pero no cuenta.
        res = self.scan("10612079703163")
        self.assertEqual(res["status"], "product_ref")
        self.assertEqual(self.op.current_product_id, self.fc4t)
        for serial in ("SNDQ703160802400391", "SNDQ703160802400393"):
            res = self.scan(serial)
            self.assertEqual(res["scan"]["lot_name"], serial[2:])
            self.assertEqual(res["scan"]["product_name"], self.fc4t.display_name)

    def test_upc_ean_and_normalized_reference(self):
        # Williams AV: UPC en Odoo, el lector lo devuelve como EAN-13.
        self.assertEqual(self.scan("0707976006110")["status"], "product_ref")
        self.assertEqual(self.op.current_product_id, self.williams)
        # Luminex: model no. con espacios contra referencia sin espacios.
        self.assertEqual(self.scan("LU 01 00072")["status"], "product_ref")
        self.assertEqual(self.op.current_product_id, self.gigacore)

    def test_neutrik_box_of_ten(self):
        self.scan("7613187014406")
        self.scan("10")  # código de "PCS": se ignora
        serials = ["10974510%02d" % n for n in range(11, 21)]
        for serial in serials:
            self.assertEqual(self.scan(serial)["status"], "ok")
        counted = self.session.scan_ids.filtered(lambda s: s.scan_type == "serial")
        self.assertEqual(sorted(counted.mapped("lot_name")), serials)
        self.assertEqual(counted.product_id, self.neutrik)

    def test_learn_product_code_in_review(self):
        self.op.current_product_id = False
        res = self.scan("X-S21-WS-EU")
        self.assertEqual(res["status"], "unknown")
        self.session.action_close_counting()
        unknown = self.session.unknown_scan_ids
        unknown.product_id = self.s21
        unknown.action_learn_product_code()
        self.assertEqual(unknown.scan_type, "product_ref")
        self.assertEqual(self.s21.product_tmpl_id.rms_scan_alias_ids.code, "X-S21-WS-EU")

        # En el siguiente recuento ya se reconoce solo (también sin guiones).
        session2 = self.env["rms.stock.count.session"].create({"location_id": self.stock.id})
        Operator = self.env["rms.stock.count.operator"]
        op2 = Operator.browse(Operator.scanner_join(session2.id, "Luis")["operator"]["id"])
        res = self.env["rms.stock.count.scan"].scanner_register(op2.id, "XS21WSEU")
        self.assertEqual(res["status"], "product_ref")
        self.assertEqual(op2.current_product_id, self.s21)

    def test_rule_serial_without_product_keeps_serial_for_review(self):
        self.op.current_product_id = False
        res = self.scan("S010040580B")
        self.assertEqual(res["status"], "unknown")
        scan = self.session.unknown_scan_ids
        self.assertEqual(scan.lot_name, "0040580")
        self.session.action_close_counting()
        scan.product_id = self.dwm
        scan.action_assign_product()
        self.assertEqual(scan.scan_type, "serial")
        self.assertEqual(scan.lot_name, "0040580")
