# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import tagged

from .common import ReceptionCommon


@tagged("post_install", "-at_install")
class TestReceptionChecklist(ReceptionCommon):

    def setUp(self):
        super().setUp()
        self.reception = self._reception([
            (self.ultra, "26476604", 1), (self.ultra, "26476605", 1), (self.ultra, "26476606", 1),
            (self.galaxy, "25110231", 1), (self.bracket, False, 3),
        ])
        self.reception.action_start()
        self.lines = self.reception.line_ids.sorted("sequence")

    def test_sequence_and_defaults(self):
        self.assertTrue(self.reception.name.startswith("REC-IN/"))
        self.assertEqual(self.reception.location_dest_id, self.warehouse.lot_stock_id)
        self.assertEqual(self.lines[0].product_state_id, self.state_new)
        self.assertTrue(self.lines[4].by_quantity)
        self.assertFalse(self.lines[0].by_quantity)
        self.assertEqual(self.reception.count_expected, 7)

    def test_green_needs_product_and_serial(self):
        result = self._scan(self.reception, "26476604")
        self.assertEqual(result["verdict"], "ok")
        line = self.lines[0]
        self.assertEqual(line.state, "received")
        self.assertEqual(line.scanned_by, self.operator)
        self.assertTrue(line.scanned_at)
        self.assertEqual(self.reception.count_received, 1)
        # Con el código del producto delante y coincidiendo: también verde
        grey = self._scan(self.reception, "0933800104")
        self.assertEqual(grey["verdict"], "product_code")
        self.assertTrue(grey["sets_context"])
        self.assertEqual(grey["product_id"], self.ultra.id)
        self.assertEqual(self._scan(self.reception, "26476605", product=self.ultra)["verdict"], "ok")
        # Minúsculas y espacios alrededor no cambian nada
        reception = self._reception([(self.rack, "168-102760", 1)])
        reception.action_start()
        self.assertEqual(self._scan(reception, " 168-102760 ")["verdict"], "ok")

    def test_repeat_does_not_count_even_with_two_operators(self):
        self.assertEqual(self._scan(self.reception, "26476604")["verdict"], "ok")
        again = self._scan(self.reception, "26476604")
        self.assertEqual(again["verdict"], "repeat")
        other = self._scan(self.reception, "26476604", user=self.operator2)
        self.assertEqual(other["verdict"], "repeat")
        self.assertIn("Operario Uno", other["message"])
        self.assertEqual(self.reception.count_received, 1)
        self.assertEqual(self.lines[0].scanned_by, self.operator)
        # Las tres lecturas quedan registradas con su autor
        scans = self.reception.scan_ids
        self.assertEqual(len(scans), 3)
        self.assertEqual(set(scans.mapped("user_id")), {self.operator, self.operator2})

    def test_resent_reading_is_not_duplicated(self):
        first = self._scan(self.reception, "26476604", client_uid="abc-1")
        second = self._scan(self.reception, "26476604", client_uid="abc-1")
        self.assertEqual(first["id"], second["id"])
        self.assertTrue(second["resent"])
        self.assertEqual(len(self.reception.scan_ids), 1)

    def test_grey_product_codes_do_not_count(self):
        for code in ("0733009338015", "0933800104", "09.338.001.04"):
            result = self._scan(self.reception, code)
            self.assertEqual(result["verdict"], "product_code", code)
            self.assertEqual(result["product_id"], self.ultra.id, code)
        # EAN válido que Odoo no conoce: gris, nunca un sobrante
        unknown = self._scan(self.reception, "8412345678905")
        self.assertEqual(unknown["verdict"], "product_code")
        self.assertFalse(unknown["sets_context"])
        self.assertEqual(self.reception.count_received, 0)
        self.assertEqual(self.reception.count_extra, 0)
        self.assertFalse(self.reception.line_ids.filtered(lambda l: l.origin == "scan"))

    def test_amber_wrong_model(self):
        result = self._scan(self.reception, "26476604", product=self.galaxy)
        self.assertEqual(result["verdict"], "wrong_model")
        line = self.lines[0]
        self.assertEqual(line.state, "wrong_model")
        self.assertEqual(line.scanned_product_id, self.galaxy)
        self.assertEqual(self.reception.count_received, 0)
        self.assertEqual(self.reception.count_review, 1)
        self.assertTrue(line.has_issue)

    def test_amber_same_serial_in_two_models_asks_for_product(self):
        reception = self._reception([(self.ultra, "SN-500", 1), (self.galaxy, "SN-500", 1)])
        reception.action_start()
        result = self._scan(reception, "SN-500")
        self.assertEqual(result["verdict"], "ambiguous")
        self.assertEqual(set(reception.line_ids.mapped("state")), {"pending"})
        result = self._scan(reception, "SN-500", product=self.galaxy)
        self.assertEqual(result["verdict"], "ok")
        self.assertEqual(reception.line_ids.filtered(lambda l: l.state == "received").product_id, self.galaxy)
        # La pistola quita «S/N:» delante, pero si la lista lo trae como parte del número también vale
        reception = self._reception([(self.rack, "SN-77001", 1), (self.rack, "77002", 1)])
        reception.action_start()
        self.assertEqual(self._scan(reception, "SN-77001")["verdict"], "ok")
        self.assertEqual(self._scan(reception, "S/N: 77002")["verdict"], "ok")

    def test_amber_probable_is_only_suggested(self):
        reception = self._reception([
            (self.rack, "168-102760", 1), (self.rack, "0012345", 1), (self.rack, "AB10O1", 1), (self.rack, "I7755", 1),
        ])
        reception.action_start()
        lines = reception.line_ids.sorted("sequence")
        for code, line in (("168102760", lines[0]), ("12345", lines[1]), ("AB1001", lines[2]), ("17755", lines[3])):
            result = self._scan(reception, code)
            self.assertEqual(result["verdict"], "probable", code)
            self.assertEqual(line.state, "probable", code)
            self.assertEqual(line.scanned_serial, code)
        self.assertEqual(reception.count_received, 0)
        self.assertEqual(reception.count_review, 4)
        # Un operario no puede confirmarla; el responsable sí
        with self.assertRaises(AccessError):
            lines[0].with_user(self.operator).action_confirm_probable()
        lines[0].with_user(self.manager).action_confirm_probable()
        self.assertEqual(lines[0].state, "received")
        # Descartada: lo leído queda como sobrante y la línea vuelve a pendiente
        lines[1].with_user(self.manager).action_reject_probable()
        self.assertEqual(lines[1].state, "pending")
        extra = reception.line_ids.filtered(lambda l: l.origin == "scan")
        self.assertEqual(extra.scanned_serial, "12345")
        self.assertEqual(extra.state, "extra")

    def test_exact_reading_wins_over_probable(self):
        reception = self._reception([(self.rack, "0012345", 1)])
        reception.action_start()
        self.assertEqual(self._scan(reception, "12345")["verdict"], "probable")
        self.assertEqual(self._scan(reception, "0012345")["verdict"], "ok")
        line = reception.line_ids.filtered(lambda l: l.origin == "list")
        self.assertEqual(line.state, "received")
        self.assertEqual(line.scanned_serial, "0012345")
        self.assertEqual(reception.line_ids.filtered(lambda l: l.origin == "scan").scanned_serial, "12345")

    def test_red_extra_is_kept(self):
        result = self._scan(self.reception, "99999999", product=self.ultra)
        self.assertEqual(result["verdict"], "extra")
        extra = self.reception.line_ids.filtered(lambda l: l.origin == "scan")
        self.assertEqual(extra.state, "extra")
        self.assertEqual(extra.product_id, self.ultra)
        self.assertEqual(extra.scanned_by, self.operator)
        self.assertEqual(self.reception.count_extra, 1)
        self.assertEqual(self._scan(self.reception, "99999999")["verdict"], "repeat")
        self.assertEqual(self.reception.count_extra, 1)

    def test_undo(self):
        self._scan(self.reception, "26476604")
        self._scan(self.reception, "77777777")
        self._scan(self.reception, "26476605", user=self.operator2)
        # Deshace la última propia: el sobrante
        self.reception.with_user(self.operator).checklist_undo()
        self.assertFalse(self.reception.line_ids.filtered(lambda l: l.origin == "scan"))
        self.reception.with_user(self.operator).checklist_undo()
        self.assertEqual(self.lines[0].state, "pending")
        self.assertFalse(self.lines[0].scanned_serial)
        self.assertEqual(self.lines[1].state, "received")
        with self.assertRaises(UserError):
            self.reception.with_user(self.operator).checklist_undo()
        # No se pierde el registro
        self.assertEqual(len(self.reception.scan_ids), 3)
        self.assertEqual(len(self.reception.scan_ids.filtered("undone")), 2)
        # Y se puede volver a leer
        self.assertEqual(self._scan(self.reception, "26476604")["verdict"], "ok")

    def test_quantity_lines(self):
        line = self.lines[4]
        result = self._scan(self.reception, "0733004033808")
        self.assertEqual(result["verdict"], "ok")
        self.assertEqual(line.qty_received, 1)
        self.assertEqual(line.state, "pending")
        line.with_user(self.operator).checklist_set_qty(3)
        self.assertEqual(line.state, "received")
        self.assertEqual(self.reception.count_received, 3)
        over = self._scan(self.reception, "4033804001")
        self.assertEqual(over["verdict"], "extra")
        self.assertEqual(line.qty_received, 4)
        self.assertTrue(line.has_issue)
        self.reception.with_user(self.operator).checklist_undo()
        self.assertEqual(line.qty_received, 3)
        self.assertFalse(line.has_issue)
        with self.assertRaises(UserError):
            self.lines[0].with_user(self.operator).checklist_set_qty(2)

    def test_manual_serial_prints_replacement_label(self):
        with self.assertRaises(UserError):
            self.reception.with_user(self.operator).checklist_manual_serial("26476604", "26476605", self.ultra.id)
        response = self.reception.with_user(self.operator).checklist_manual_serial(
            "26476604", "26476604", self.ultra.id)
        self.assertEqual(response["result"]["verdict"], "ok")
        self.assertTrue(self.lines[0].manual_entry)
        action = response["print_action"]
        self.assertEqual(action["tag"], "rms_print_label")
        self.assertIn("/report/pdf/rms_stock_lot_label_print.report_lot_label_10x5_document/", action["params"]["url"])
        lot = self.env["stock.lot"].search([("name", "=", "26476604"), ("product_id", "=", self.ultra.id)])
        self.assertEqual(len(lot), 1)
        self.assertTrue(lot.rms_replacement_label)

    def test_damaged(self):
        line = self.lines[0]
        with self.assertRaises(UserError):
            line.with_user(self.operator).checklist_set_damaged("Golpe en la esquina")
        self._scan(self.reception, "26476604")
        with self.assertRaises(UserError):
            line.with_user(self.operator).checklist_set_damaged("")
        line.with_user(self.operator).checklist_set_damaged("Golpe en la esquina")
        self.assertEqual(line.state, "damaged")
        self.assertEqual(line.damage_note, "Golpe en la esquina")
        self.assertEqual(self.reception.count_review, 1)
        line.with_user(self.operator).checklist_set_damaged(damaged=False)
        self.assertEqual(line.state, "received")

    def test_blind_reception_reconciles_when_document_arrives(self):
        reception = self._reception()
        reception.action_start()
        self.assertTrue(reception.checklist_state()["reception"]["blind"])
        for code in ("26476604", "26476605", "0026476606", "88888888"):
            self.assertEqual(self._scan(reception, code)["verdict"], "extra")
        self._scan(reception, "0733004033808")
        self._scan(reception, "0733004033808")
        self.assertEqual(reception.count_extra, 6)
        wizard = self.env["rms.reception.load.wizard"].with_user(self.operator).create({
            "reception_id": reception.id, "source": "paste",
            "paste_text": "0933800104\t26476604\n0933800104\t26476605\n0933800104\t26476606\n"
                          "0933800104\t26476607\n4033804001\t\t3\n",
        })
        wizard.action_read()
        self.assertEqual(wizard.line_ids.mapped("product_id"), self.ultra | self.bracket)
        wizard.action_confirm()
        by_serial = {l.serial: l for l in reception.line_ids if l.origin == "list" and l.serial}
        self.assertEqual(by_serial["26476604"].state, "received")
        self.assertEqual(by_serial["26476604"].scanned_by, self.operator)
        self.assertEqual(by_serial["26476605"].state, "received")
        self.assertEqual(by_serial["26476606"].state, "probable")
        self.assertEqual(by_serial["26476607"].state, "pending")
        qty_line = reception.line_ids.filtered(lambda l: l.origin == "list" and l.by_quantity)
        self.assertEqual(qty_line.qty_received, 2)
        extras = reception.line_ids.filtered(lambda l: l.origin == "scan")
        self.assertEqual(extras.mapped("scanned_serial"), ["88888888"])
        self.assertEqual(reception.count_received, 4)
        self.assertEqual(reception.count_extra, 1)
        # Las lecturas siguen enlazadas a su línea y se pueden deshacer
        self.assertEqual(self._scan(reception, "26476604")["verdict"], "repeat")

    def test_checklist_state_payload(self):
        self._scan(self.reception, "26476604")
        self._scan(self.reception, "55555555")
        state = self.reception.with_user(self.operator).checklist_state()
        self.assertEqual(state["counters"]["expected"], 7)
        self.assertEqual(state["counters"]["received"], 1)
        self.assertEqual(state["counters"]["extra"], 1)
        self.assertEqual([g["name"] for g in state["groups"]], ["ULTRA-X40", "GALAXY 816", "MUB-X40 U-Bracket"])
        self.assertEqual((state["groups"][0]["done"], state["groups"][0]["total"]), (1, 3))
        self.assertEqual(len(state["extras"]), 1)
        self.assertFalse(state["can_manage"])
        self.assertEqual(state["scans"][0]["verdict"], "extra")

    def test_no_readings_after_finish(self):
        self.reception.with_user(self.operator).action_finish()
        self.assertEqual(self.reception.state, "review")
        with self.assertRaises(UserError):
            self._scan(self.reception, "26476604")


@tagged("post_install", "-at_install")
class TestReceptionStock(ReceptionCommon):

    def _quantity(self, product, location=None):
        return self.env["stock.quant"]._get_available_quantity(product, location or self.warehouse.lot_stock_id)

    def test_full_flow_creates_validated_receipt(self):
        reception = self._reception([
            (self.ultra, "26476604", 1), (self.ultra, "26476605", 1), (self.ultra, "26476606", 1),
            (self.galaxy, "25110231", 1), (self.galaxy, "25110232", 1), (self.bracket, False, 3),
        ])
        lines = reception.line_ids.sorted("sequence")
        lines[1].product_state_id = self.state_demo
        reception.with_user(self.operator).action_open_checklist()
        self.assertEqual(reception.state, "receiving")
        self._scan(reception, "26476604")
        self._scan(reception, "26476605")
        self._scan(reception, "25110231")
        lines[3].with_user(self.operator).checklist_set_damaged("Caja abierta")
        self._scan(reception, "25110232", product=self.ultra)        # modelo distinto
        self._scan(reception, "90000001", product=self.ultra)        # sobrante que se aceptará
        self._scan(reception, "90000002", product=self.ultra)        # sobrante que se deja fuera
        lines[5].with_user(self.operator).checklist_set_qty(2)
        reception.with_user(self.operator).action_finish()
        self.assertEqual(lines[2].state, "missing")
        self.assertEqual(lines[5].state, "missing")

        # El operario no puede dar entrada
        with self.assertRaises(AccessError):
            reception.with_user(self.operator).action_validate_stock()
        manager_reception = reception.with_user(self.manager)
        # Con incidencias sin decidir tampoco entra nada
        with self.assertRaises(UserError):
            manager_reception.action_validate_stock()
        self.assertEqual(reception.state, "review")
        with self.assertRaises(UserError):
            lines[2].with_user(self.manager).action_res_accept()     # un faltante no se «acepta»
        with self.assertRaises(AccessError):
            lines[2].with_user(self.operator).action_res_claim()
        lines[2].with_user(self.manager).action_res_claim()
        lines[5].with_user(self.manager).action_res_backorder()
        lines[3].with_user(self.manager).action_res_reject()         # dañado: fuera
        lines[4].with_user(self.manager).action_res_reject()         # modelo distinto: fuera
        extras = reception.line_ids.filtered(lambda l: l.origin == "scan").sorted("scanned_serial")
        extras[0].with_user(self.manager).action_res_accept()
        extras[1].with_user(self.manager).action_res_reject()
        self.assertEqual(reception.count_unresolved, 0)
        manager_reception.action_validate_stock()

        self.assertEqual(reception.state, "done")
        picking = reception.picking_id
        self.assertEqual(picking.state, "done")
        self.assertEqual(picking.picking_type_id, self.warehouse.in_type_id)
        self.assertEqual(picking.partner_id, self.supplier)
        self.assertEqual(picking.company_id, self.company)
        self.assertIn(reception.name, picking.origin)
        lots = picking.move_line_ids.lot_id
        self.assertEqual(sorted(lots.mapped("name")), ["26476604", "26476605", "90000001"])
        states = {lot.name: lot.product_state_id for lot in lots}
        self.assertEqual(states["26476604"], self.state_new)
        self.assertEqual(states["26476605"], self.state_demo)
        self.assertEqual(self._quantity(self.ultra), 3)
        self.assertEqual(self._quantity(self.galaxy), 0)
        self.assertEqual(self._quantity(self.bracket), 2)
        self.assertFalse(self.env["stock.lot"].search([("name", "in", ("90000002", "26476606", "25110231"))]))
        self.assertEqual(lines[0].lot_id.name, "26476604")
        # Cerrada: no admite más cambios
        with self.assertRaises(UserError):
            manager_reception.action_validate_stock()
        with self.assertRaises(UserError):
            manager_reception.action_cancel()

    def test_accepted_wrong_model_enters_with_read_product(self):
        reception = self._reception([(self.galaxy, "25110232", 1)])
        reception.action_start()
        self._scan(reception, "25110232", product=self.ultra)
        reception.action_finish()
        reception.line_ids.with_user(self.manager).action_res_accept()
        reception.with_user(self.manager).action_validate_stock()
        lot = reception.picking_id.move_line_ids.lot_id
        self.assertEqual(lot.product_id, self.ultra)
        self.assertEqual(lot.name, "25110232")

    def test_probable_must_be_resolved_and_confirmed_serial_is_the_read_one(self):
        reception = self._reception([(self.rack, "168-102760", 1)])
        reception.action_start()
        self._scan(reception, "168102760")
        reception.action_finish()
        self.assertEqual(reception.line_ids.state, "probable")
        with self.assertRaises(UserError):
            reception.with_user(self.manager).action_validate_stock()
        reception.with_user(self.manager).action_confirm_all_probable()
        reception.with_user(self.manager).action_validate_stock()
        self.assertEqual(reception.picking_id.move_line_ids.lot_id.name, "168102760")

    def test_existing_pending_receipt_is_used(self):
        picking = self.env["stock.picking"].create({
            "picking_type_id": self.warehouse.in_type_id.id, "partner_id": self.supplier.id,
            "location_id": self.env.ref("stock.stock_location_suppliers").id,
            "location_dest_id": self.warehouse.lot_stock_id.id,
            "move_ids": [(0, 0, {
                "product_id": self.ultra.id, "product_uom_qty": 3, "product_uom": self.ultra.uom_id.id,
                "location_id": self.env.ref("stock.stock_location_suppliers").id,
                "location_dest_id": self.warehouse.lot_stock_id.id,
            })],
        })
        picking.action_confirm()
        reception = self._reception(
            [(self.ultra, "26476604", 1), (self.ultra, "26476605", 1), (self.ultra, "26476606", 1)],
            picking_id=picking.id)
        reception.action_start()
        self._scan(reception, "26476604")
        self._scan(reception, "26476605")
        reception.action_finish()
        reception.with_user(self.manager).action_all_missing_backorder()
        reception.with_user(self.manager).action_validate_stock()
        self.assertEqual(picking.state, "done")
        self.assertEqual(reception.picking_id, picking)
        self.assertEqual(sorted(picking.move_line_ids.lot_id.mapped("name")), ["26476604", "26476605"])
        backorder = self.env["stock.picking"].search([("backorder_id", "=", picking.id)])
        self.assertEqual(len(backorder), 1)
        self.assertEqual(backorder.move_ids.product_uom_qty, 1)
        self.assertEqual(self._quantity(self.ultra), 2)

    def test_serial_already_in_stock_is_refused(self):
        lot = self.env["stock.lot"].create({"name": "26476604", "product_id": self.ultra.id})
        self.env["stock.quant"]._update_available_quantity(self.ultra, self.warehouse.lot_stock_id, 1, lot_id=lot)
        reception = self._reception([(self.ultra, "26476604", 1)])
        reception.action_start()
        self._scan(reception, "26476604")
        reception.action_finish()
        with self.assertRaises(UserError):
            reception.with_user(self.manager).action_validate_stock()

    def test_line_without_product_blocks_entry(self):
        reception = self._reception([(False, "ZZ-1001", 1)])
        reception.action_start()
        self.assertEqual(self._scan(reception, "ZZ-1001")["verdict"], "ok")
        reception.action_finish()
        with self.assertRaises(UserError):
            reception.with_user(self.manager).action_validate_stock()
        reception.line_ids.product_id = self.rack.id
        reception.with_user(self.manager).action_validate_stock()
        self.assertEqual(reception.picking_id.move_line_ids.lot_id.product_id, self.rack)

    def test_nothing_received_closes_without_picking(self):
        reception = self._reception([(self.ultra, "26476604", 1)])
        reception.action_start()
        reception.action_finish()
        reception.line_ids.with_user(self.manager).action_res_claim()
        reception.with_user(self.manager).action_validate_stock()
        self.assertEqual(reception.state, "done")
        self.assertFalse(reception.picking_id)

    def test_reopen(self):
        reception = self._reception([(self.ultra, "26476604", 1)])
        reception.action_start()
        reception.action_finish()
        with self.assertRaises(AccessError):
            reception.with_user(self.operator).action_reopen()
        reception.with_user(self.manager).action_reopen()
        self.assertEqual(reception.line_ids.state, "pending")
        self.assertEqual(self._scan(reception, "26476604")["verdict"], "ok")

    def test_reports(self):
        reception = self._reception([(self.ultra, "26476604", 1), (self.ultra, "26476605", 1)])
        reception.action_start()
        self._scan(reception, "26476604")
        self._scan(reception, "44444444")
        reception.action_finish()
        html = self.env["ir.actions.report"]._render_qweb_html(
            "rms_stock_reception_check.report_rms_reception", reception.ids)[0].decode()
        for text in ("26476604", "26476605", "44444444", "Falta", "Sobrante", reception.name):
            self.assertIn(text, html)
        action = reception.action_export_xlsx()
        self.assertEqual(action["type"], "ir.actions.act_url")
        attachment = self.env["ir.attachment"].search([
            ("res_model", "=", "rms.reception"), ("res_id", "=", reception.id), ("name", "like", ".xlsx")])
        self.assertTrue(attachment.datas)

    def test_multicompany(self):
        company_b = self.env["res.company"].create({"name": "Espacio Test"})
        warehouse_b = self.env["stock.warehouse"].search([("company_id", "=", company_b.id)], limit=1)
        self.assertTrue(warehouse_b)
        self.manager.write({"company_ids": [(4, company_b.id)]})
        reception_a = self._reception([(self.ultra, "26476604", 1)])
        reception_b = self.env["rms.reception"].with_company(company_b).create({
            "partner_id": self.supplier.id, "company_id": company_b.id,
        })
        self.assertEqual(reception_b.warehouse_id, warehouse_b)
        self.assertEqual(reception_b.location_dest_id, warehouse_b.lot_stock_id)
        self.env["rms.reception.line"].create({
            "reception_id": reception_b.id, "product_id": self.ultra.id, "serial": "26476699",
        })
        # El operario solo está en la empresa A: no ve ni toca la recepción de B
        Reception = self.env["rms.reception"].with_user(self.operator)
        self.assertIn(reception_a, Reception.search([]))
        self.assertNotIn(reception_b, Reception.search([]))
        self.assertFalse(self.env["rms.reception.line"].with_user(self.operator).search(
            [("reception_id", "=", reception_b.id)]))
        with self.assertRaises(AccessError):
            reception_b.with_user(self.operator).checklist_state()
        # Un almacén de otra empresa no vale
        with self.assertRaises(Exception):
            reception_b.warehouse_id = self.warehouse.id
            reception_b.flush_recordset()
        reception_b.invalidate_recordset()
        # El responsable (con las dos empresas) recibe en B y el stock entra en B
        manager_b = reception_b.with_user(self.manager).with_company(company_b)
        manager_b.action_start()
        self.assertEqual(manager_b.checklist_scan("26476699")["result"]["verdict"], "ok")
        manager_b.action_finish()
        manager_b.action_validate_stock()
        picking = reception_b.picking_id
        self.assertEqual(picking.company_id, company_b)
        self.assertEqual(picking.picking_type_id.warehouse_id, warehouse_b)
        self.assertEqual(picking.state, "done")
        self.assertEqual(self._quantity(self.ultra, warehouse_b.lot_stock_id), 1)
        self.assertEqual(self._quantity(self.ultra), 0)
