# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import tagged

from .common import ReceptionCommon


@tagged("post_install", "-at_install")
class TestReceptionRequired(ReceptionCommon):

    def setUp(self):
        super().setUp()
        self.in_type = self.warehouse.in_type_id
        self.in_type.rms_reception_required = True

    def _incoming(self, products):
        picking = self.env["stock.picking"].create({
            "picking_type_id": self.in_type.id, "partner_id": self.supplier.id,
            "location_id": self.supplier.property_stock_supplier.id,
            "location_dest_id": self.warehouse.lot_stock_id.id,
            "move_ids": [(0, 0, {
                "product_id": p.id, "product_uom_qty": q, "product_uom": p.uom_id.id,
                "location_id": self.supplier.property_stock_supplier.id,
                "location_dest_id": self.warehouse.lot_stock_id.id,
            }) for p, q in products],
        })
        picking.action_confirm()
        return picking

    def test_serial_picking_blocks_manual_validation(self):
        picking = self._incoming([(self.ultra, 1)])
        self.assertTrue(picking.rms_reception_mandatory)
        with self.assertRaisesRegex(UserError, "Recepción de proveedor"):
            picking.with_user(self.operator).button_validate()
        self.assertNotEqual(picking.state, "done")

    def test_quantity_only_and_off_are_free(self):
        picking = self._incoming([(self.bracket, 3)])
        self.assertFalse(picking.rms_reception_mandatory)
        picking.move_ids.quantity = 3
        picking.with_user(self.operator).button_validate()
        self.assertEqual(picking.state, "done")
        self.in_type.rms_reception_required = False
        other = self._incoming([(self.ultra, 1)])
        self.assertFalse(other.rms_reception_mandatory)

    def test_reception_module_still_validates(self):
        reception = self._reception([(self.ultra, "REQ-001", 1), (self.bracket, False, 2)])
        reception.action_start()
        self._scan(reception, "REQ-001")
        self._scan(reception, self.bracket.barcode)
        self._scan(reception, self.bracket.barcode)
        reception.with_user(self.operator).action_finish()
        reception.with_user(self.manager).action_validate_stock()
        self.assertEqual(reception.state, "done")
        self.assertEqual(reception.picking_id.state, "done")

    def test_manager_skip_with_reason(self):
        picking = self._incoming([(self.ultra, 1)])
        with self.assertRaises(AccessError):
            picking.with_user(self.operator).action_rms_skip_reception()
        with self.assertRaises(UserError):
            picking.with_user(self.manager)._rms_validate_skipping_reception(" ")
        picking.move_ids.move_line_ids.unlink()
        self.env["stock.move.line"].create({
            "move_id": picking.move_ids.id, "picking_id": picking.id, "product_id": self.ultra.id,
            "product_uom_id": self.ultra.uom_id.id, "lot_name": "REQ-SKIP", "quantity": 1,
            "location_id": picking.location_id.id, "location_dest_id": picking.location_dest_id.id,
            "product_state_id": self.state_new.id,
        })
        picking.move_ids.picked = True
        wizard = self.env["rms.reception.skip.wizard"].with_user(self.manager).create({
            "picking_id": picking.id, "reason": "Caja abierta en el muelle"})
        wizard.action_confirm()
        self.assertEqual(picking.state, "done")
        body = " ".join(picking.message_ids.mapped("body"))
        self.assertIn("Caja abierta en el muelle", body)
        self.assertIn(self.manager.name, body)
