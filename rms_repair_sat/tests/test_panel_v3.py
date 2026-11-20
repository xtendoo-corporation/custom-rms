from datetime import timedelta

from odoo import Command, fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSatPanel(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({'name': 'Cliente panel'})
        cls.product = cls.env['product.product'].create({'name': 'Equipo panel', 'is_storable': True})

    def _repair(self, **values):
        return self.env['repair.order'].create(dict({
            'partner_id': self.customer.id, 'product_id': self.product.id,
            'rms_site': 'madrid',
        }, **values))

    def test_stage_history_and_indirect_state_change(self):
        repair = self._repair()
        initial = repair.rms_stage_log_ids
        self.assertEqual(len(initial), 1)
        self.assertEqual(initial.stage, 'received')
        self.assertFalse(initial.date_out)
        repair.rms_stage = 'diagnosis'
        self.assertTrue(initial.date_out)
        self.assertEqual(len(repair.rms_stage_log_ids), 2)
        repair.rms_stage = 'diagnosis'
        self.assertEqual(len(repair.rms_stage_log_ids), 2)
        repair.write({'state': 'confirmed'})
        logs = repair.rms_stage_log_ids
        self.assertEqual(len(logs), 3)
        self.assertEqual(logs.filtered(lambda log: not log.date_out).stage, 'repair')
        self.assertEqual(logs.filtered(lambda log: not log.date_out).user_id, self.env.user)
        self.assertTrue(all(log.days >= 0 for log in logs))

    def test_lead_days_and_idempotent_initialization(self):
        repair = self._repair(rms_entry_date=fields.Datetime.now() - timedelta(days=5))
        repair.rms_stage = 'delivered'
        self.assertEqual(repair.rms_close_date, fields.Date.context_today(repair))
        self.assertEqual(repair.rms_lead_days, 5)
        count = len(repair.rms_stage_log_ids)
        self.env['repair.order']._rms_initialize_panel()
        self.env['repair.order']._rms_initialize_panel()
        self.assertEqual(len(repair.rms_stage_log_ids), count)
        self.assertEqual(len(repair.rms_stage_log_ids.filtered(lambda log: not log.date_out)), 1)

    def test_late_filter_and_ra_action(self):
        repair = self._repair()
        repair.write({'rms_stage': 'diagnosis'})
        repair.rms_stage_date = fields.Datetime.now() - timedelta(days=8, minutes=1)
        self.assertIn(repair, self.env['repair.order'].search([('rms_late', '=', True)]))
        repair.rms_stage = 'delivered'
        self.assertNotIn(repair, self.env['repair.order'].search([('rms_late', '=', True)]))
        action = self.env['stock.quant'].action_rms_ra_quants()
        self.assertEqual(action['res_model'], 'stock.quant')
        self.assertEqual(action['view_mode'], 'list')

    def test_posted_invoice_and_refund_amounts(self):
        order = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [Command.create({'product_id': self.product.id, 'product_uom_qty': 1, 'price_unit': 100})],
        })
        repair = self._repair(sale_order_id=order.id)
        # Se vinculan líneas de factura a la venta como en la facturación de Odoo.
        invoices = self.env['account.move'].create([
            {'move_type': kind, 'partner_id': self.customer.id,
             'invoice_line_ids': [Command.create({'name': 'Servicio', 'quantity': 1, 'price_unit': price,
                                                  'sale_line_ids': [Command.set(order.order_line.ids)]})]}
            for kind, price in [('out_invoice', 100), ('out_refund', 20)]
        ])
        invoices.action_post()
        repair._rms_refresh_panel_amounts()
        self.assertAlmostEqual(repair.rms_amount_invoiced, 80)
        self.assertAlmostEqual(repair.rms_margin, 80 - repair.rms_parts_cost)
        invoices[1].button_draft()
        repair._rms_refresh_panel_amounts()
        self.assertAlmostEqual(repair.rms_amount_invoiced, 100)

    def test_done_parts_are_included_in_margin(self):
        self.product.standard_price = 12
        repair = self._repair()
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', repair.company_id.id)], limit=1)
        stock = warehouse.lot_stock_id
        production = warehouse._get_production_location()
        self.env['stock.quant']._update_available_quantity(self.product, stock, 2)
        move = self.env['stock.move'].create({
            'product_id': self.product.id, 'product_uom': self.product.uom_id.id,
            'product_uom_qty': 2, 'location_id': stock.id, 'location_dest_id': production.id,
            'company_id': repair.company_id.id, 'repair_id': repair.id, 'repair_line_type': 'add',
            'move_line_ids': [Command.create({'product_id': self.product.id,
                'product_uom_id': self.product.uom_id.id, 'quantity': 2,
                'location_id': stock.id, 'location_dest_id': production.id,
                'company_id': repair.company_id.id})],
        })
        move._action_confirm()
        move.picked = True
        move._action_done()
        repair._rms_refresh_panel_amounts()
        self.assertAlmostEqual(repair.rms_parts_cost, move.value)
        self.assertAlmostEqual(repair.rms_margin, repair.rms_amount_invoiced - move.value)
