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
        self.assertIn("Etiqueta sustituta", html)
        self.assertIn(self.demo.name, html)

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
