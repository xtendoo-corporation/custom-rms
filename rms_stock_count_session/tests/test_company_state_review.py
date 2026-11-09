# -*- coding: utf-8 -*-
from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCompanyStateReview(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.other = cls.env['res.company'].create({'name': 'Espacio recuento test'})
        cls.env.user.company_ids |= cls.other
        cls.env = cls.env(context=dict(cls.env.context, allowed_company_ids=[cls.company.id, cls.other.id]))
        cls.warehouse = cls.env['stock.warehouse'].search([('company_id', '=', cls.company.id)], limit=1)
        cls.warehouse.code = 'RMS7'
        cls.target = cls.env['stock.warehouse'].with_company(cls.other).search([('company_id', '=', cls.other.id)], limit=1)
        if not cls.target:
            cls.target = cls.env['stock.warehouse'].with_company(cls.other).create({
                'name': 'Espacio 7', 'code': 'ET7', 'company_id': cls.other.id,
            })
        else:
            cls.target.code = 'ET7'
        cls.product = cls.env['product.product'].create({
            'name': 'Equipo compartido', 'tracking': 'serial', 'is_storable': True, 'company_id': False,
        })
        cls.demo = cls.env.ref('rms_product_state.state_demo')
        cls.used = cls.env.ref('rms_product_state.state_second_hand')

    def session(self):
        return self.env['rms.stock.count.session'].create({
            'location_id': self.warehouse.lot_stock_id.id, 'company_id': self.company.id,
        })

    def line(self, session, serial, company=False):
        return self.env['rms.stock.count.line'].create({
            'session_id': session.id, 'product_id': self.product.id, 'lot_name': serial,
            'location_id': session.location_id.id, 'company_id': (company or self.company).id,
            'product_state_id': self.demo.id, 'counted_qty': 1, 'status': 'unexpected', 'to_apply': True,
        })

    def test_company_destinations_and_state(self):
        session = self.session()
        session.write({'state': 'review', 'counting_date': '2026-01-15'})
        first = self.line(session, 'OWNER-RMS')
        second = self.line(session, 'OWNER-ET', self.other)
        second.product_state_id = self.used
        session.action_apply_to_inventory()
        for line, company, location, state in [
            (first, self.company, self.warehouse.lot_stock_id, self.demo),
            (second, self.other, self.target.lot_stock_id, self.used),
        ]:
            self.assertEqual(line.lot_id.company_id, company)
            self.assertEqual(line.lot_id.product_state_id, state)
            quant = self.env['stock.quant'].with_company(company).search([('lot_id', '=', line.lot_id.id)])
            self.assertEqual(quant.location_id, location)
            self.assertEqual(quant.inventory_quantity, 1)
            self.assertEqual(quant.inventory_date, fields.Date.to_date('2026-01-15'))
            self.assertEqual(quant.quantity, 0)  # Adjustment remains pending.
            quant.action_apply_inventory()
            self.assertEqual(quant.quantity, 1)
            self.assertEqual(line.lot_id.product_state_id, state)

    def test_doubtful_or_missing_company_blocks(self):
        session = self.session()
        session.state = 'review'
        line = self.line(session, 'DOUBTFUL')
        line.company_doubtful = True
        with self.assertRaises(UserError):
            session.action_apply_to_inventory()
        line.write({'company_id': False})
        with self.assertRaises(UserError):
            session.action_apply_to_inventory()

    def test_majority_tie_latest_and_preserve_manual_product(self):
        session = self.session()
        operator = self.env['rms.stock.count.operator'].create({'session_id': session.id, 'name': 'Ana'})
        for state in [self.demo, self.used, self.demo]:
            self.env['rms.stock.count.scan'].create({
                'session_id': session.id, 'operator_id': operator.id, 'raw_code': 'VOTE',
                'code': 'VOTE', 'scan_type': 'serial', 'product_id': self.product.id,
                'lot_name': 'VOTE', 'location_id': session.location_id.id,
                'product_state_id': state.id, 'quantity': 1,
            })
        session._build_reconciliation()
        line = session.line_ids.filtered(lambda l: l.lot_name == 'VOTE')
        self.assertEqual(line.product_state_id, self.demo)
        scan = session.scan_ids[0].copy({'product_state_id': self.used.id})
        scan.scanned_at = fields.Datetime.now()
        session._build_reconciliation()
        line = session.line_ids.filtered(lambda l: l.lot_name == 'VOTE')
        self.assertEqual(line.product_state_id, self.used)
        replacement = self.env['product.product'].create({
            'name': 'Producto corregido', 'is_storable': True, 'tracking': self.product.tracking,
        })
        line.write({'product_id': replacement.id, 'company_id': self.other.id, 'product_state_id': self.demo.id})
        session._build_reconciliation()
        line = session.line_ids.filtered(lambda l: l.lot_name == 'VOTE')
        self.assertEqual(len(line), 1)
        self.assertEqual(line.product_id, replacement)
        self.assertEqual(line.company_id, self.other)
        self.assertEqual(line.product_state_id, self.demo)

    def test_sage_assignment_and_ambiguity(self):
        session = self.session()
        session.state = 'review'
        first = self.line(session, 'SAGE-01')
        second = self.line(session, 'SAGE-02')
        category = self.env['product.category'].create({'name': 'Marca recuento'})
        for company, code, serial in [(self.company, '01', 'SAGE-01'), (self.other, '02', 'SAGE-02')]:
            snapshot = self.env['rms.sage.snapshot'].with_company(company).create({
                'name': 'Snapshot ' + code, 'company_id': company.id,
                'sage_company_code': code, 'brand_categ_id': category.id, 'state': 'current',
            })
            self.env['rms.sage.stock.line'].create({
                'snapshot_id': snapshot.id, 'is_current': True, 'warehouse_code': '7',
                'article_code': 'PRODUCT', 'model_code': 'PRODUCT', 'serial': serial,
                'product_id': self.product.id,
            })
        session.action_assign_company_from_sage()
        self.assertEqual(first.company_id, self.company)
        self.assertEqual(second.company_id, self.other)
        second_match = self.env['rms.sage.stock.line'].search([('serial', '=', 'SAGE-02')])
        second_match.copy({'serial': 'SAGE-01'})
        session.action_assign_company_from_sage()
        self.assertTrue(first.company_doubtful)
        with self.assertRaises(UserError):
            session.action_apply_to_inventory()
        first.company_id = self.company
        self.assertFalse(first.company_doubtful)

    def test_replacement_label_shared_company(self):
        wizard = self.env['rms.lot.label.wizard'].with_company(self.other).create({
            'product_id': self.product.id, 'serial_text': 'SHARED-LABEL',
            'serial_confirm': 'SHARED-LABEL', 'product_state_id': self.demo.id,
        })
        lot = wizard._get_or_create_lots(['SHARED-LABEL'])
        self.assertFalse(lot.company_id)
        self.assertEqual(lot.product_state_id, self.demo)

    def test_scanner_review_and_existing_lot_state(self):
        session = self.session()
        Operator = self.env['rms.stock.count.operator']
        joined = Operator.scanner_join(session.id, 'Operario integrado')
        operator = Operator.browse(joined['operator']['id'])
        operator.current_product_id = self.product
        operator.scanner_set_state(self.demo.id)
        result = self.env['rms.stock.count.scan'].scanner_register(operator.id, 'INTEGRATED-STATE')
        self.assertEqual(result['status'], 'ok')
        session.action_close_counting()
        line = session.line_ids.filtered(lambda line: line.lot_name == 'INTEGRATED-STATE')
        self.assertEqual(line.product_state_id, self.demo)
        line.product_state_id = self.used
        session.action_apply_to_inventory()
        self.assertEqual(line.lot_id.product_state_id, self.used)
        quant = self.env['stock.quant'].search([('lot_id', '=', line.lot_id.id)])
        quant.action_apply_inventory()
        self.assertEqual(line.lot_id.product_state_id, self.used)

        followup = self.session()
        followup.state = 'review'
        existing = self.line(followup, line.lot_name)
        existing.lot_id = line.lot_id
        followup.action_apply_to_inventory()
        self.assertEqual(line.lot_id.product_state_id, self.demo)

    def test_replacement_label_reuses_owned_lot(self):
        owned = self.env['stock.lot'].create({
            'name': 'OWNED-LABEL', 'product_id': self.product.id, 'company_id': self.company.id,
        })
        wizard = self.env['rms.lot.label.wizard'].create({
            'product_id': self.product.id, 'serial_text': owned.name, 'serial_confirm': owned.name,
        })
        self.assertEqual(wizard._get_or_create_lots([owned.name]), owned)
