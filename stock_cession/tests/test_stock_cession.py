from odoo import Command, _
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged
from odoo.tests.common import new_test_user


@tagged('post_install', '-at_install')
class TestStockCession(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company_b = cls.env['res.company'].create({'name': 'Cesiones B'})
        cls.user = new_test_user(
            cls.env, login='stock_cession_user', groups='stock.group_stock_user',
            company_id=cls.company.id,
            company_ids=[Command.set(cls.company.ids)],
        )
        cls.manager = new_test_user(
            cls.env, login='stock_cession_manager', groups='stock.group_stock_manager',
            company_id=cls.company.id,
            company_ids=[Command.set(cls.company.ids)],
        )
        cls.partner = cls.env['res.partner'].create({'name': 'Cliente cesiones'})
        cls.product = cls.env['product.product'].create({
            'name': 'Producto cesiones', 'type': 'consu',
        })
        cls.source = cls.env['stock.location'].create({
            'name': 'Origen cesiones', 'usage': 'internal',
            'company_id': cls.company.id,
        })
        cls.destination = cls.env.ref('stock.stock_location_customers')
        cls.picking_type = cls.env['stock.picking.type'].create({
            'name': 'Cesiones', 'code': 'outgoing', 'sequence_code': 'CES_TEST',
            'company_id': cls.company.id,
            'default_location_src_id': cls.source.id,
            'default_location_dest_id': cls.destination.id,
        })

    def _cession(self, **values):
        vals = {
            'partner_id': self.partner.id, 'product_id': self.product.id,
            'location_src_id': self.source.id,
            'location_dest_id': self.destination.id,
            'company_id': self.company.id,
        }
        vals.update(values)
        return self.env['stock.cession'].sudo().create(vals)

    def test_draft_requires_cancel(self):
        for state in ('draft', 'done'):
            cession = self._cession(state=state)
            with self.assertRaises(UserError):
                cession.with_user(self.user).action_draft()
        cession = self._cession(state='cancel').with_user(self.user)
        cession.action_draft()
        self.assertEqual(cession.state, 'draft')

    def test_confirm_twice_keeps_one_picking(self):
        cession = self._cession().with_user(self.user)
        cession.action_confirm()
        picking = cession.picking_id
        self.assertEqual(picking.state, 'done')
        self.assertEqual(picking.company_id, self.company)
        self.assertEqual(picking.picking_type_id, self.picking_type)
        count = self.env['stock.picking'].search_count([])
        with self.assertRaises(UserError):
            cession.action_confirm()
        # También protege registros históricos con un estado incoherente.
        cession.sudo().write({'state': 'draft'})
        with self.assertRaises(UserError):
            cession.action_confirm()
        cession.sudo().write({'state': 'cancel'})
        with self.assertRaises(UserError):
            cession.action_draft()
        self.assertEqual(cession.picking_id, picking)
        self.assertEqual(self.env['stock.picking'].search_count([]), count)

    def test_company_rule(self):
        cession_a = self._cession()
        source_b = self.source.copy({'company_id': self.company_b.id})
        cession_b = self._cession(
            company_id=self.company_b.id, location_src_id=source_b.id,
        )
        visible = self.env['stock.cession'].with_user(self.user).with_context(
            allowed_company_ids=self.company.ids,
        ).search([('id', 'in', (cession_a | cession_b).ids)])
        self.assertEqual(visible.ids, cession_a.ids)

    def test_confirm_preserves_move_description(self):
        cession = self._cession().with_user(self.user)
        cession.action_confirm()
        move = cession.picking_id.move_ids
        self.assertEqual(len(move), 1)
        self.assertEqual(move.description_picking, _('Cesion ') + cession.name)
        self.assertEqual(move.product_id, self.product)
        self.assertEqual(move.product_uom_qty, cession.quantity)
        self.assertEqual(move.product_uom, cession.uom_id)
        self.assertEqual(move.location_id, self.source)
        self.assertEqual(move.location_dest_id, self.destination)
        self.assertEqual(cession.picking_id.state, 'done')

    def test_picking_type_uses_cession_company(self):
        source_b = self.source.copy({'company_id': self.company_b.id})
        destination_b = self.source.copy({
            'name': 'Destino cesiones B', 'company_id': self.company_b.id,
        })
        picking_type_b = self.env['stock.picking.type'].create({
            'name': 'Cesiones B', 'sequence_code': 'CES_TEST_B',
            'company_id': self.company_b.id,
            'code': 'internal',
            'default_location_src_id': source_b.id,
            'default_location_dest_id': destination_b.id,
        })
        cession = self._cession(
            company_id=self.company_b.id, location_src_id=source_b.id,
            location_dest_id=destination_b.id,
        ).with_user(self.manager).with_context(
            allowed_company_ids=(self.company | self.company_b).ids,
        )
        self.manager.company_ids = self.company | self.company_b
        cession.action_confirm()
        self.assertEqual(cession.picking_id.picking_type_id, picking_type_b)
        self.assertEqual(cession.picking_id.company_id, self.company_b)

    def test_protected_fields(self):
        cession = self._cession().with_user(self.user)
        for vals in ({'state': 'done'}, {'picking_id': False}):
            with self.assertRaises(UserError):
                cession.write(vals)
        cession.action_cancel()
        self.assertEqual(cession.state, 'cancel')

    def test_unlink_permissions_and_done(self):
        cession = self._cession()
        with self.assertRaises(AccessError):
            cession.with_user(self.user).unlink()
        cession.with_user(self.manager).unlink()
        done = self._cession(state='done')
        with self.assertRaises(UserError):
            done.with_user(self.manager).unlink()
