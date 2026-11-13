# -*- coding: utf-8 -*-
"""C3.8: la Valoración de Sage (existencias) incluye lo que está en depósito
en casa de clientes. Los "Depósitos de venta" se cargan aparte y marcan esas
existencias para que no cuenten como "falta en la nave"."""
import base64

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSageDeposits(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.brand = cls.env['product.category'].create({'name': 'RMSTEST Deposit Brand'})
        cls.product = cls.env['product.product'].create({
            'name': 'DEPOSIT TEST SPEAKER', 'default_code': 'DEPTEST-ART', 'categ_id': cls.brand.id,
            'is_storable': True, 'tracking': 'serial'})
        Warehouse = cls.env['rms.sage.warehouse']
        cls.sage_wh = Warehouse.search([('sage_company_code', '=', '01'), ('code', '=', 'AL1')], limit=1) or \
            Warehouse.create({'sage_company_code': '01', 'code': 'AL1', 'name': 'AL1'})
        stock_wh = cls.env['stock.warehouse'].search([('company_id', '=', cls.env.company.id)], limit=1)
        cls.session = cls.env['rms.stock.count.session'].create({'location_id': stock_wh.lot_stock_id.id})
        Operator = cls.env['rms.stock.count.operator']
        cls.operator = Operator.browse(Operator.scanner_join(cls.session.id, 'Depósitos')['operator']['id'])
        cls.Scan = cls.env['rms.stock.count.scan']
        cls.Line = cls.env['rms.sage.stock.line']

    def _csv(self, rows):
        body = ''.join('AL1;DEPTEST-ART;Altavoz;;%s\n;;;%s;%s\n' % (qty, serial, qty) for serial, qty in rows)
        return ('Almacén;Artículo;Nombre artículo;Lotes;Unidades\n' + body).encode('utf-8')

    def _load(self, rows, kind='stock', **values):
        vals = {'scope': 'brand', 'brand_categ_id': self.brand.id, 'sage_company_code': '01',
                'stock_kind': kind, 'filename': '%s.csv' % kind, 'file_data': base64.b64encode(self._csv(rows))}
        vals.update(values)
        return self.env['rms.stock.count.sage.import'].create(vals).action_import()

    def _line(self, serial, kind='stock'):
        return self.Line.search([('serial', '=', serial), ('stock_kind', '=', kind), ('is_current', '=', True)])

    def _load_both(self):
        self._load([('DEP-1', '1,00'), ('DEP-2', '1,00'), ('DEP-3', '1,00')])
        # DEP-1 está en casa de un cliente; DEP-2 es un depósito negativo
        # (devuelto de más en Sage): no marca nada.
        self._load([('DEP-1', '1,00'), ('DEP-2', '-1,00')], kind='deposit')

    def test_deposit_marks_stock_line(self):
        self._load_both()
        self.assertTrue(self._line('DEP-1').in_deposit)
        self.assertFalse(self._line('DEP-2').in_deposit)
        self.assertFalse(self._line('DEP-3').in_deposit)
        deposit = self._line('DEP-1', 'deposit')
        self.assertEqual(deposit.stock_kind, 'deposit')
        self.assertFalse(deposit.in_deposit)
        # Estar en existencias y en depósitos no es un duplicado.
        self.assertLessEqual(self._line('DEP-1').dup_count, 1)
        self.assertEqual(deposit.dup_count, 0)

    def test_same_file_as_other_kind_is_not_already_loaded(self):
        rows = [('DEP-9', '1,00')]
        self._load(rows)
        self._load(rows, kind='deposit')  # mismo contenido, otro tipo: no es "ya cargado"
        self.assertTrue(self._line('DEP-9', 'deposit'))

    def test_replacing_one_kind_keeps_the_other(self):
        self._load_both()
        deposit_snapshot = self._line('DEP-1', 'deposit').snapshot_id
        self._load([('DEP-1', '1,00'), ('DEP-4', '1,00')])  # nuevas existencias
        self.assertEqual(deposit_snapshot.state, 'current')
        self.assertFalse(self._line('DEP-3'), 'Las existencias viejas se reemplazan')
        self.assertTrue(self._line('DEP-1').in_deposit)
        stock_snapshot = self._line('DEP-4').snapshot_id
        self._load([('DEP-4', '1,00')], kind='deposit')  # nuevos depósitos
        self.assertEqual(stock_snapshot.state, 'current')
        self.assertEqual(deposit_snapshot.state, 'replaced')
        self.assertFalse(self._line('DEP-1').in_deposit, 'Ya no está en depósito')
        self.assertTrue(self._line('DEP-4').in_deposit)

    def test_scan_of_deposit_serial_is_amber(self):
        self._load_both()
        self.assertEqual(self.session.sage_mode, 'global')
        self.operator.current_product_id = False
        verdict = self.Scan.scanner_register(self.operator.id, 'DEP-1')['sage']
        self.assertEqual(verdict['v'], 'dep')
        self.assertEqual(verdict['n'], 1)
        self.operator.current_product_id = False
        self.assertEqual(self.Scan.scanner_register(self.operator.id, 'DEP-3')['sage']['v'], 'ok')
        # En modo zona también avisa.
        self.session.sage_mode = 'scope'
        verdicts = self.Scan._sage_verdict(['DEP-1'], self.session, [self.product.id])
        self.assertEqual(verdicts[0]['v'], 'dep')

    def test_checklist_and_missing_skip_deposits(self):
        self._load_both()
        Checklist = self.env['rms.sage.checklist']
        rows = {row.serial: row for row in Checklist.search([('serial', 'like', 'DEP-')])}
        self.assertEqual(set(rows), {'DEP-1', 'DEP-2', 'DEP-3'}, 'Las líneas de depósito no salen en el checklist')
        self.assertTrue(rows['DEP-1'].in_deposit)
        self.assertEqual(rows['DEP-1'].pending_qty, 0)
        self.assertEqual(rows['DEP-3'].pending_qty, 1)
        self.session.write({'sage_mode': 'scope', 'sage_company_code': '01',
                            'brand_categ_ids': [(6, 0, self.brand.ids)],
                            'sage_warehouse_ids': [(6, 0, self.sage_wh.ids)]})
        expected = self.session._sage_lines()
        self.assertEqual(set(expected.mapped('serial')), {'DEP-2', 'DEP-3'})
