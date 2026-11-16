from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import new_test_user

from ..models.tools import clean_code, is_valid_gtin
from .common import DeliveryCheckCommon


@tagged('post_install', '-at_install')
class TestDeliveryCheck(DeliveryCheckCommon):

    def test_tools(self):
        self.assertEqual(clean_code("EASN0'0005\r"), 'EASN0-0005')
        self.assertEqual(clean_code('S/N: 12345'), '12345')
        self.assertTrue(is_valid_gtin('8412345678905'))
        self.assertFalse(is_valid_gtin('8412345678906'))

    def test_colors_green_duplicate_grey_red(self):
        a = self._lot(self.galaxy, 'GLX-A')
        self._lot(self.galaxy, 'GLX-B')
        self._lot(self.galaxy, 'GLX-C')
        self._lot(self.console, 'SD12-1')
        self._lot(self.galaxy, 'GLX-GONE', stock=False)
        other_loc = self.env['stock.location'].create({
            'name': 'Otra nave', 'usage': 'internal', 'company_id': self.company.id})
        self._lot(self.galaxy, 'GLX-ELSEWHERE', location=other_loc)
        picking = self._picking([(self.galaxy, 2), (self.cover, 3)])
        self.assertEqual(picking.rms_check_kind, 'sale')

        scan = self._scan(picking, 'GLX-A')
        self.assertEqual((scan.result, scan.reason), ('ok', 'ok'))
        self.assertEqual(scan.user_id, self.operator)
        self.assertTrue(scan.scanned_at)
        self.assertEqual(scan.move_id.product_id, self.galaxy)
        self.assertEqual(picking.rms_check_state, 'in_progress')
        # segunda lectura = ya leído (no cuenta dos veces)
        self.assertEqual(self._scan(picking, 'GLX-A').result, 'duplicate')
        # apóstrofo de la pistola con teclado inglés
        self.assertEqual(self._scan(picking, "GLX'A").result, 'duplicate')
        # EAN del producto: gris
        grey = self._scan(picking, '8412345678905')
        self.assertEqual((grey.result, grey.reason), ('grey', 'product_code'))
        self.assertEqual(self._scan(picking, '4006381333931').result, 'grey')
        # rojos
        self.assertEqual(self._scan(picking, 'NO-EXISTE').reason, 'unknown')
        self.assertEqual(self._scan(picking, 'SD12-1').reason, 'not_in_picking')
        self.assertEqual(self._scan(picking, 'GLX-GONE').reason, 'already_out')
        self.assertEqual(self._scan(picking, 'GLX-ELSEWHERE').reason, 'not_in_stock')
        self.assertEqual(self._scan(picking, 'GLX-B').result, 'ok')
        over = self._scan(picking, 'GLX-C')
        self.assertEqual((over.result, over.reason), ('red', 'over_qty'))
        self.assertTrue(over.is_incident)

        state = picking.with_user(self.operator).rms_check_get_state()
        self.assertEqual(state['counters']['read'], 2)
        self.assertEqual(state['counters']['missing'], 3)  # las 3 fundas
        self.assertEqual(state['counters']['blocked'], 5)
        self.assertEqual(state['groups'][0]['done'], 2)
        self.assertTrue(state['groups'][1]['by_qty'])
        # todo queda guardado
        self.assertEqual(len(picking.rms_check_scan_ids), 11)
        self.assertEqual(a.product_state_id, self.states['new'])

    def test_undo_keeps_reading(self):
        self._lot(self.galaxy, 'GLX-A')
        picking = self._picking([(self.galaxy, 1)])
        scan = self._scan(picking, 'GLX-A')
        picking.with_user(self.operator).rms_check_undo(scan.id)
        self.assertTrue(scan.undone)
        self.assertEqual(scan.undone_by_id, self.operator)
        self.assertEqual(picking._rms_summary()['read'], 0)
        self.assertEqual(self._scan(picking, 'GLX-A').result, 'ok')

    def test_demo_blocked_in_sale(self):
        self._lot(self.galaxy, 'GLX-DEMO', state='demo')
        picking = self._picking([(self.galaxy, 1)])
        scan = self._scan(picking, 'GLX-DEMO')
        self.assertEqual((scan.result, scan.reason), ('red', 'demo_sale'))
        with self.assertRaises(UserError):
            picking.with_user(self.operator).rms_check_finish()

    def test_fixed_serial_vs_any_of_state(self):
        fixed = self._lot(self.galaxy, 'GLX-EX1', state='ex_demo')
        self._lot(self.galaxy, 'GLX-EX2', state='ex_demo')
        self._lot(self.console, 'SD12-EX', state='ex_demo')
        self._lot(self.console, 'SD12-NEW')
        picking = self._sale_picking([
            {'product_id': self.galaxy.id, 'product_uom_qty': 1,
             'serial_ids': [Command.create({'lot_id': fixed.id})]},
            {'product_id': self.console.id, 'product_uom_qty': 1,
             'rms_requested_state_id': self.states['ex_demo'].id},
        ])
        # serie fijada: otra del mismo estado NO vale sin administrador
        wrong = self._scan(picking, 'GLX-EX2')
        self.assertEqual((wrong.result, wrong.reason, wrong.approval_state), ('amber', 'serial_mismatch', 'pending'))
        picking.with_user(self.operator).rms_check_undo(wrong.id)
        self.assertEqual(self._scan(picking, 'GLX-EX1').result, 'ok')
        # «el que sea» de Ex-Demo: uno nuevo no coincide con el pedido
        mismatch = self._scan(picking, 'SD12-NEW')
        self.assertEqual((mismatch.result, mismatch.reason), ('amber', 'state_mismatch'))
        picking.with_user(self.operator).rms_check_undo(mismatch.id)
        good = self._scan(picking, 'SD12-EX')
        self.assertEqual(good.result, 'ok')
        self.assertTrue(good.needs_review)

    def test_review_mandatory(self):
        self._lot(self.console, 'SD12-EX', state='ex_demo')
        picking = self._sale_picking([{
            'product_id': self.console.id, 'product_uom_qty': 1,
            'rms_requested_state_id': self.states['ex_demo'].id}])
        scan = self._scan(picking, 'SD12-EX')
        with self.assertRaisesRegex(UserError, 'Revisado'):
            picking.with_user(self.operator).rms_check_finish()
        picking.with_user(self.operator).rms_check_set_reviewed(scan.id, True)
        self.assertEqual(scan.reviewed_by_id, self.operator)
        self.assertEqual(picking.with_user(self.operator).rms_check_finish()['status'], 'ready')
        picking.with_user(self.operator).rms_check_validate()
        self.assertEqual(picking.state, 'done')
        self.assertEqual(picking.rms_check_state, 'done')
        self.assertEqual(picking.move_line_ids.lot_id.name, 'SD12-EX')

    def test_amber_needs_manager(self):
        ex = self._lot(self.galaxy, 'GLX-EX', state='ex_demo')
        self._lot(self.galaxy, 'GLX-NEW')
        picking = self._picking([(self.galaxy, 1)])  # salida manual: se espera Nuevo
        scan = self._scan(picking, 'GLX-EX')
        self.assertEqual(scan.reason, 'state_mismatch')
        picking.with_user(self.operator).rms_check_set_reviewed(scan.id, True)
        self.assertEqual(picking.with_user(self.operator).rms_check_finish()['status'], 'pending_admin')
        self.assertEqual(picking.rms_check_state, 'pending_admin')
        with self.assertRaises(UserError):
            picking.with_user(self.operator).rms_check_validate()
        with self.assertRaises(AccessError):
            picking.with_user(self.operator).rms_check_approve(scan.id)
        with self.assertRaises(UserError):
            self._scan(picking, 'GLX-NEW')
        with self.assertRaises(UserError):
            picking.with_user(self.operator).button_validate()
        picking.with_user(self.manager).rms_check_approve(scan.id, 'Hablado con el cliente')
        self.assertEqual((scan.approval_state, scan.approved_by_id), ('approved', self.manager))
        self.assertEqual(picking.rms_check_state, 'ready')
        picking.with_user(self.operator).rms_check_validate()
        self.assertEqual(picking.state, 'done')
        self.assertEqual(picking.move_line_ids.lot_id, ex)
        # el equipo conserva su estado (no se copia el «Nuevo» de la reserva)
        self.assertEqual(ex.product_state_id, self.states['ex_demo'])

    def test_rejected_amber_does_not_leave(self):
        self._lot(self.galaxy, 'GLX-EX', state='ex_demo')
        new = self._lot(self.galaxy, 'GLX-NEW')
        picking = self._picking([(self.galaxy, 1)])
        scan = self._scan(picking, 'GLX-EX')
        picking.with_user(self.operator).rms_check_set_reviewed(scan.id, True)
        picking.with_user(self.operator).rms_check_finish()
        picking.with_user(self.manager).rms_check_reject(scan.id, 'No')
        self.assertEqual(picking.rms_check_state, 'pending_admin')  # falta una unidad
        picking.with_user(self.manager).rms_check_reopen()
        self.assertEqual(self._scan(picking, 'GLX-NEW').result, 'ok')
        self.assertEqual(picking.with_user(self.operator).rms_check_finish()['status'], 'ready')
        picking.with_user(self.operator).rms_check_validate()
        self.assertEqual(picking.move_line_ids.lot_id, new)

    def test_partial_only_manager(self):
        a = self._lot(self.galaxy, 'GLX-A')
        self._lot(self.galaxy, 'GLX-B')
        picking = self._picking([(self.galaxy, 2), (self.cover, 2)])
        self._scan(picking, 'GLX-A')
        picking.with_user(self.operator).rms_check_set_qty(picking.move_ids[1].id, 2)
        with self.assertRaises(UserError):
            picking.with_user(self.operator).rms_check_set_qty(picking.move_ids[1].id, 5)
        self.assertEqual(picking.with_user(self.operator).rms_check_finish()['status'], 'pending_admin')
        with self.assertRaises(AccessError):
            picking.with_user(self.operator).rms_check_decide_partial('backorder')
        with self.assertRaises(UserError):
            picking.with_user(self.operator).rms_check_validate()
        picking.with_user(self.manager).rms_check_decide_partial('backorder')
        self.assertEqual(picking.rms_check_state, 'ready')
        picking.with_user(self.operator).rms_check_validate()
        self.assertEqual(picking.state, 'done')
        self.assertEqual(picking.move_line_ids.lot_id, a)
        self.assertEqual(sum(picking.move_ids.filtered(lambda m: m.product_id == self.cover).mapped('quantity')), 2)
        backorder = self.env['stock.picking'].search([('backorder_id', '=', picking.id)])
        self.assertEqual(len(backorder), 1)
        self.assertEqual(backorder.move_ids.product_id, self.galaxy)
        self.assertEqual(backorder.move_ids.product_uom_qty, 1)
        self.assertEqual(backorder.rms_check_state, 'none')

    def test_partial_without_backorder(self):
        self._lot(self.galaxy, 'GLX-A')
        self._lot(self.galaxy, 'GLX-B')
        picking = self._picking([(self.galaxy, 2)])
        self._scan(picking, 'GLX-A')
        picking.with_user(self.operator).rms_check_finish()
        picking.with_user(self.manager).rms_check_decide_partial('no_backorder')
        picking.with_user(self.manager).rms_check_validate()
        self.assertEqual(picking.state, 'done')
        self.assertFalse(self.env['stock.picking'].search([('backorder_id', '=', picking.id)]))

    def test_validate_writes_scanned_lots(self):
        """Odoo reserva A y B; el operario coge B y C: salen B y C, A se queda."""
        a = self._lot(self.galaxy, 'GLX-A')
        b = self._lot(self.galaxy, 'GLX-B')
        c = self._lot(self.galaxy, 'GLX-C')
        picking = self._picking([(self.galaxy, 2)])
        self.assertEqual(picking.move_line_ids.lot_id, a | b)
        other = self._picking([(self.galaxy, 1)])  # otro albarán reserva C «el que sea»
        self.assertEqual(other.move_line_ids.lot_id, c)
        self._scan(picking, 'GLX-B')
        self._scan(picking, 'GLX-C')
        picking.with_user(self.operator).rms_check_finish()
        picking.with_user(self.operator).rms_check_validate()
        self.assertEqual(picking.state, 'done')
        self.assertEqual(picking.move_line_ids.lot_id, b | c)
        Quant = self.env['stock.quant']
        self.assertEqual(Quant._get_available_quantity(self.galaxy, self.stock, lot_id=b, strict=True), 0)
        self.assertEqual(Quant._get_available_quantity(self.galaxy, self.customers, lot_id=c, strict=True), 1)
        # el otro albarán se queda con A
        self.assertEqual(other.move_line_ids.lot_id, a)
        self.assertEqual(Quant.search([('lot_id', '=', a.id), ('location_id', '=', self.stock.id)]).quantity, 1)

    def test_validate_from_sublocation(self):
        shelf = self.env['stock.location'].create({
            'name': 'Estante 1', 'usage': 'internal', 'location_id': self.stock.id})
        self._lot(self.galaxy, 'GLX-A')
        b = self._lot(self.galaxy, 'GLX-SHELF', location=shelf)
        picking = self._picking([(self.galaxy, 1)])
        self._scan(picking, 'GLX-SHELF')
        picking.with_user(self.operator).rms_check_finish()
        picking.with_user(self.operator).rms_check_validate()
        self.assertEqual(picking.move_line_ids.location_id, shelf)
        self.assertFalse(self.env['stock.quant'].search([
            ('lot_id', '=', b.id), ('location_id', '=', shelf.id), ('quantity', '!=', 0)]))

    def test_validate_blocked_outside_checklist(self):
        self._lot(self.galaxy, 'GLX-A')
        picking = self._picking([(self.galaxy, 1)])
        self._scan(picking, 'GLX-A')
        with self.assertRaisesRegex(UserError, 'checklist'):
            picking.button_validate()
        picking.with_user(self.manager).rms_check_reset()
        self.assertEqual(picking.rms_check_state, 'none')
        self.assertTrue(all(picking.rms_check_scan_ids.mapped('undone')))
        # tipo de operación con checklist obligatorio
        picking.picking_type_id.rms_check_required = True
        with self.assertRaisesRegex(UserError, 'checklist'):
            picking.button_validate()

    # ------------------------------------------------------------ paquetes
    def _pack(self, lots, name='4 Galaxy 2M'):
        return self.env['rms.used.pack'].with_user(self.manager).create({
            'name': name, 'lot_ids': [Command.set(lots.ids)]})

    def _used_picking(self, qty):
        return self._sale_picking([{
            'product_id': self.galaxy.id, 'product_uom_qty': qty,
            'rms_requested_state_id': self.states['second_hand'].id}])

    def test_pack_complete(self):
        lots = self._lot(self.galaxy, 'GLX-2M1', 'second_hand') | self._lot(self.galaxy, 'GLX-2M2', 'second_hand')
        pack = self._pack(lots)
        self.assertEqual(pack.authorized_by_id, self.manager)
        picking = self._used_picking(2)
        first = self._scan(picking, 'GLX-2M1')
        self.assertEqual((first.result, first.reason), ('amber', 'pack_incomplete'))
        second = self._scan(picking, 'GLX-2M2')
        self.assertEqual((first.result, second.result), ('ok', 'ok'))
        self.assertEqual(first.approval_state, 'none')
        for scan in first | second:
            picking.with_user(self.operator).rms_check_set_reviewed(scan.id, True)
        self.assertEqual(picking.with_user(self.operator).rms_check_finish()['status'], 'ready')
        picking.with_user(self.operator).rms_check_validate()
        self.assertEqual(pack.state, 'sold')
        self.assertEqual(lots.mapped('product_state_id'), self.states['second_hand'])
        # deshacer uno devuelve el paquete a incompleto (en otro albarán)

    def test_pack_incomplete_then_broken_by_manager(self):
        lots = self._lot(self.galaxy, 'GLX-2M1', 'second_hand') | self._lot(self.galaxy, 'GLX-2M2', 'second_hand')
        pack = self._pack(lots)
        picking = self._used_picking(1)
        scan = self._scan(picking, 'GLX-2M1')
        self.assertEqual(scan.reason, 'pack_incomplete')
        picking.with_user(self.operator).rms_check_set_reviewed(scan.id, True)
        self.assertEqual(picking.with_user(self.operator).rms_check_finish()['status'], 'pending_admin')
        with self.assertRaises(AccessError):
            picking.with_user(self.operator).rms_check_approve(scan.id)
        with self.assertRaises(UserError):
            pack.with_user(self.operator).action_break()
        picking.with_user(self.manager).rms_check_approve(scan.id, 'El cliente solo quiere una')
        self.assertEqual(pack.state, 'broken')
        self.assertEqual(pack.broken_by_id, self.manager)
        self.assertIn(picking.name, pack.broken_reason)
        self.assertEqual(picking.rms_check_state, 'ready')
        picking.with_user(self.operator).rms_check_validate()
        self.assertEqual(picking.move_line_ids.lot_id.name, 'GLX-2M1')
        # el otro equipo del paquete roto ya puede salir suelto
        picking2 = self._used_picking(1)
        self.assertEqual(self._scan(picking2, 'GLX-2M2').result, 'ok')

    def test_pack_undo_goes_back_to_incomplete(self):
        lots = self._lot(self.galaxy, 'GLX-2M1', 'second_hand') | self._lot(self.galaxy, 'GLX-2M2', 'second_hand')
        self._pack(lots)
        picking = self._used_picking(2)
        first = self._scan(picking, 'GLX-2M1')
        second = self._scan(picking, 'GLX-2M2')
        picking.with_user(self.operator).rms_check_undo(second.id)
        self.assertEqual((first.result, first.reason, first.approval_state), ('amber', 'pack_incomplete', 'pending'))

    def test_second_hand_without_pack(self):
        self._lot(self.galaxy, 'GLX-2M9', 'second_hand')
        picking = self._used_picking(1)
        scan = self._scan(picking, 'GLX-2M9')
        self.assertEqual((scan.result, scan.reason), ('amber', 'used_no_pack'))
        picking.with_user(self.operator).rms_check_set_reviewed(scan.id, True)
        self.assertEqual(picking.with_user(self.operator).rms_check_finish()['status'], 'pending_admin')
        picking.with_user(self.manager).rms_check_approve(scan.id)
        picking.with_user(self.operator).rms_check_validate()
        self.assertEqual(picking.state, 'done')

    def test_pack_constraints(self):
        new = self._lot(self.galaxy, 'GLX-N')
        used = self._lot(self.galaxy, 'GLX-2M1', 'second_hand')
        with self.assertRaises(ValidationError):
            self._pack(new)
        self._pack(used)
        with self.assertRaises(ValidationError):
            self._pack(used, name='Otro')
        with self.assertRaises(AccessError):
            self.env['rms.used.pack'].with_user(self.operator).create({'name': 'X'})

    # ------------------------------------------------------- permisos / empresas
    def test_state_change_only_manager(self):
        lot = self._lot(self.galaxy, 'GLX-A')
        with self.assertRaises(AccessError):
            lot.with_user(self.operator).write({'product_state_id': self.states['demo'].id})
        lot.with_user(self.manager).write({'product_state_id': self.states['demo'].id})
        self.assertEqual(lot.product_state_id, self.states['demo'])

    def test_reception_still_sets_state_for_operator(self):
        """La recepción (rms_product_state) sigue copiando el estado elegido."""
        picking = self.env['stock.picking'].with_user(self.operator).create({
            'picking_type_id': self.warehouse.in_type_id.id,
            'location_id': self.env.ref('stock.stock_location_suppliers').id,
            'location_dest_id': self.stock.id,
            'move_ids': [Command.create({
                'product_id': self.galaxy.id, 'product_uom_qty': 1, 'product_uom': self.galaxy.uom_id.id,
                'location_id': self.env.ref('stock.stock_location_suppliers').id,
                'location_dest_id': self.stock.id,
            })],
        })
        picking.action_confirm()
        picking.move_ids.move_line_ids.unlink()
        self.env['stock.move.line'].with_user(self.operator).create({
            'move_id': picking.move_ids.id, 'picking_id': picking.id, 'product_id': self.galaxy.id,
            'lot_name': 'GLX-IN-2M', 'quantity': 1, 'product_state_id': self.states['second_hand'].id,
            'location_id': picking.location_id.id, 'location_dest_id': self.stock.id,
        })
        picking.move_ids.picked = True
        picking.with_user(self.operator).button_validate()
        lot = self.env['stock.lot'].search([('name', '=', 'GLX-IN-2M')])
        self.assertEqual(lot.product_state_id, self.states['second_hand'])

    def test_multicompany(self):
        company_b = self.env['res.company'].create({'name': 'Espacio (test)'})
        warehouse_b = self.env['stock.warehouse'].search([('company_id', '=', company_b.id)], limit=1)
        user_b = new_test_user(
            self.env, login='c2_operario_b', groups='stock.group_stock_user',
            company_id=company_b.id, company_ids=[Command.set(company_b.ids)])
        self._lot(self.galaxy, 'GLX-A')
        picking = self._picking([(self.galaxy, 1)])
        self._scan(picking, 'GLX-A')
        # la otra empresa ni ve ni toca
        with self.assertRaises(AccessError):
            picking.with_user(user_b).rms_check_scan('GLX-A')
        self.assertFalse(self.env['rms.delivery.scan'].with_user(user_b).search([]))
        # mismo nº de serie en la otra empresa: cada albarán usa el de su empresa
        lot_b = self._lot(self.galaxy, 'GLX-A', location=warehouse_b.lot_stock_id, company=company_b)
        picking_b = self._picking([(self.galaxy, 1)], warehouse=warehouse_b)
        scan_b = self.env['rms.delivery.scan'].browse(
            picking_b.with_user(user_b).with_company(company_b).rms_check_scan('GLX-A')['scan_id'])
        self.assertEqual((scan_b.result, scan_b.lot_id, scan_b.company_id), ('ok', lot_b, company_b))
        self.assertEqual(self.env['rms.delivery.scan'].with_user(user_b).search([]), scan_b)
        pack_b = self.env['rms.used.pack'].create({'name': 'B', 'company_id': company_b.id})
        self.assertFalse(self.env['rms.used.pack'].with_user(self.manager).search([('id', '=', pack_b.id)]))

    def test_report_renders(self):
        self._lot(self.galaxy, 'GLX-A')
        picking = self._picking([(self.galaxy, 1)])
        self._scan(picking, 'GLX-A')
        picking.with_user(self.operator).rms_check_finish()
        picking.with_user(self.operator).rms_check_validate()
        html = self.env['ir.actions.report']._render_qweb_html(
            'rms_stock_delivery_check.report_delivery_serials', picking.ids)[0].decode()
        self.assertIn('GLX-A', html)
        self.assertIn('Nuevo', html)
