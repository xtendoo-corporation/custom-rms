from odoo import Command
from odoo.tests import TransactionCase
from odoo.tests.common import new_test_user


class DeliveryCheckCommon(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.warehouse = cls.env['stock.warehouse'].search([('company_id', '=', cls.company.id)], limit=1)
        cls.stock = cls.warehouse.lot_stock_id
        cls.customers = cls.warehouse.out_type_id.default_location_dest_id
        cls.operator = new_test_user(
            cls.env, login='c2_operario', groups='stock.group_stock_user',
            company_id=cls.company.id, company_ids=[Command.set(cls.company.ids)])
        cls.manager = new_test_user(
            cls.env, login='c2_responsable', groups='stock.group_stock_manager',
            company_id=cls.company.id, company_ids=[Command.set(cls.company.ids)])
        cls.partner = cls.env['res.partner'].create({'name': 'Cliente checklist'})
        cls.states = {
            code: cls.env.ref('rms_product_state.state_%s' % code)
            for code in ('new', 'demo', 'ex_demo', 'second_hand')
        }
        cls.galaxy = cls._product('Galaxy 816', 'serial')
        cls.console = cls._product('Consola SD12', 'serial')
        cls.cover = cls._product('Funda Galaxy', 'none', barcode='8412345678905')
        cls.env['stock.quant']._update_available_quantity(cls.cover, cls.stock, 20)

    @classmethod
    def _product(cls, name, tracking, **vals):
        return cls.env['product.product'].create(dict({
            'name': name, 'type': 'consu', 'is_storable': True, 'tracking': tracking,
            'list_price': 100.0,
        }, **vals))

    @classmethod
    def _lot(cls, product, name, state='new', location=None, stock=True, company=None):
        lot = cls.env['stock.lot'].create({
            'name': name, 'product_id': product.id, 'product_state_id': cls.states[state].id,
            'company_id': (company or cls.company).id,
        })
        if stock:
            cls.env['stock.quant']._update_available_quantity(product, location or cls.stock, 1, lot_id=lot)
        return lot

    def _picking(self, lines, warehouse=None):
        """Albarán de salida manual, confirmado y reservado."""
        warehouse = warehouse or self.warehouse
        customers = warehouse.out_type_id.default_location_dest_id
        picking = self.env['stock.picking'].create({
            'partner_id': self.partner.id,
            'picking_type_id': warehouse.out_type_id.id,
            'location_id': warehouse.lot_stock_id.id,
            'location_dest_id': customers.id,
            'company_id': warehouse.company_id.id,
            'move_ids': [Command.create({
                'product_id': product.id, 'product_uom_qty': qty, 'product_uom': product.uom_id.id,
                'location_id': warehouse.lot_stock_id.id, 'location_dest_id': customers.id,
                'company_id': warehouse.company_id.id,
            }) for product, qty in lines],
        })
        picking.action_confirm()
        picking.action_assign()
        return picking

    def _sale_picking(self, line_vals):
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [Command.create(vals) for vals in line_vals],
        })
        order.action_confirm()
        self.assertEqual(len(order.picking_ids), 1)
        return order.picking_ids

    def _scan(self, picking, code, user=None):
        result = picking.with_user(user or self.operator).rms_check_scan(code)
        picking.invalidate_recordset()
        return self.env['rms.delivery.scan'].browse(result['scan_id'])
