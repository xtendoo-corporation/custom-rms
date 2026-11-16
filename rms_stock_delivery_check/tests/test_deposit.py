from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import DeliveryCheckCommon


@tagged('post_install', '-at_install')
class TestDeposit(DeliveryCheckCommon):

    def _deposit(self, lines):
        Cession = self.env['stock.cession'].with_user(self.operator)
        defaults = Cession.default_get(['location_src_id', 'location_dest_id', 'company_id'])
        return Cession.create(dict(defaults, partner_id=self.partner.id, rms_line_ids=[
            Command.create({'product_id': product.id, 'quantity': qty}) for product, qty in lines]))

    def test_deposit_out_and_return(self):
        demo = self._lot(self.galaxy, 'GLX-DEMO', 'demo')
        new = self._lot(self.galaxy, 'GLX-NEW')
        self._lot(self.galaxy, 'GLX-OTHER')
        deposit = self._deposit([(self.galaxy, 2), (self.cover, 2)])
        self.assertEqual(deposit.location_src_id, self.stock)
        self.assertEqual(deposit.location_dest_id.usage, 'transit')
        self.assertTrue(deposit.location_dest_id.rms_customer_deposit)
        self.assertEqual(deposit.rms_deposit_state, 'draft')
        with self.assertRaises(UserError):
            deposit.action_confirm()  # la cesión clásica no vale con varias líneas

        action = deposit.action_rms_prepare_out()
        self.assertEqual(action['tag'], 'rms_stock_delivery_check.checklist')
        out = deposit.picking_id
        self.assertEqual(out.rms_check_kind, 'deposit_out')
        self.assertEqual(out.state, 'assigned')
        self.assertEqual(deposit.rms_deposit_state, 'preparing')
        self.assertEqual(deposit.state, 'draft')

        # en un depósito SÍ puede salir un Demo, y no se exige estado
        self.assertEqual(self._scan(out, 'GLX-DEMO').result, 'ok')
        self.assertEqual(self._scan(out, 'GLX-NEW').result, 'ok')
        out.with_user(self.operator).rms_check_set_qty(out.move_ids.filtered(
            lambda m: m.product_id == self.cover).id, 2)
        self.assertEqual(out.with_user(self.operator).rms_check_finish()['status'], 'ready')
        out.with_user(self.operator).rms_check_validate()
        self.assertEqual(out.state, 'done')
        self.assertEqual(deposit.state, 'done')
        self.assertEqual(deposit.rms_deposit_state, 'out')
        self.assertEqual(deposit.rms_out_count, 4)
        units = deposit.rms_unit_ids.sudo()
        self.assertEqual(units.lot_id, demo | new)
        self.assertEqual(len(units), 3)
        self.assertEqual(demo.product_state_id, self.states['demo'])
        quant = self.env['stock.quant'].search([('lot_id', '=', demo.id), ('quantity', '>', 0)])
        self.assertEqual(quant.location_id, deposit.location_dest_id)

        # 12 días después vuelve solo el Demo
        units.write({'date_out': fields.Datetime.now() - timedelta(days=12)})
        units.invalidate_recordset()
        self.assertEqual(units[0].days_out, 12)
        deposit.invalidate_recordset()
        self.assertEqual(deposit.rms_days_out, 12)
        deposit.with_user(self.operator).action_rms_register_return()
        back = deposit.rms_picking_ids.filtered(lambda p: p.rms_deposit_role == 'return')
        self.assertEqual(back.rms_check_kind, 'deposit_return')
        self.assertEqual(back.location_dest_id, self.stock)
        # algo que no salió en este depósito no puede «volver»
        self.assertEqual(self._scan(back, 'GLX-OTHER').result, 'red')
        scan = self._scan(back, 'GLX-DEMO')
        self.assertEqual(scan.result, 'ok')
        self.assertFalse(scan.needs_review)
        state = back.with_user(self.operator).rms_check_get_state()
        self.assertEqual(len(state['outside']), 3)
        self.assertEqual([u['back'] for u in state['outside'] if u['serial'] == 'GLX-DEMO'], [True])
        self.assertEqual(state['outside'][0]['days'], 12)
        # vuelta parcial: la valida el operario, lo demás sigue en el cliente
        self.assertEqual(back.with_user(self.operator).rms_check_finish()['status'], 'ready')
        back.with_user(self.operator).rms_check_validate()
        self.assertEqual(back.state, 'done')
        self.assertFalse(self.env['stock.picking'].search([('backorder_id', '=', back.id)]))
        self.assertEqual(deposit.rms_deposit_state, 'partial')
        self.assertEqual(deposit.rms_out_count, 3)
        returned = units.filtered(lambda u: u.state == 'returned')
        self.assertEqual(returned.lot_id, demo)
        self.assertEqual(returned.return_picking_id, back)
        quant = self.env['stock.quant'].search([('lot_id', '=', demo.id), ('quantity', '>', 0)])
        self.assertEqual(quant.location_id, self.stock)

        # segunda vuelta: el resto
        deposit.with_user(self.operator).action_rms_register_return()
        back2 = deposit.rms_picking_ids.filtered(
            lambda p: p.rms_deposit_role == 'return' and p.state != 'done')
        self.assertEqual(sum(back2.move_ids.mapped('product_uom_qty')), 3)
        self.assertEqual(self._scan(back2, 'GLX-DEMO').result, 'red')  # ya volvió
        self.assertEqual(self._scan(back2, 'GLX-NEW').result, 'ok')
        back2.with_user(self.operator).rms_check_set_qty(back2.move_ids.filtered(
            lambda m: m.product_id == self.cover).id, 2)
        back2.with_user(self.operator).rms_check_finish()
        back2.with_user(self.operator).rms_check_validate()
        self.assertEqual(deposit.rms_deposit_state, 'returned')
        self.assertEqual(deposit.rms_out_count, 0)
        with self.assertRaises(UserError):
            deposit.action_rms_register_return()

    def test_deposit_out_partial_needs_manager(self):
        self._lot(self.galaxy, 'GLX-A')
        deposit = self._deposit([(self.galaxy, 2)])
        deposit.action_rms_prepare_out()
        out = deposit.picking_id
        self._scan(out, 'GLX-A')
        self.assertEqual(out.with_user(self.operator).rms_check_finish()['status'], 'pending_admin')
        out.with_user(self.manager).rms_check_decide_partial('no_backorder')
        out.with_user(self.operator).rms_check_validate()
        self.assertEqual(deposit.rms_out_count, 1)

    def test_classic_cession_untouched(self):
        cession = self.env['stock.cession'].create({
            'partner_id': self.partner.id, 'product_id': self.cover.id, 'quantity': 2,
            'location_src_id': self.stock.id, 'location_dest_id': self.customers.id,
        })
        cession.action_confirm()
        self.assertEqual(cession.state, 'done')
        self.assertEqual(cession.picking_id.state, 'done')
        self.assertFalse(cession.rms_unit_ids)
