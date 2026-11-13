# -*- coding: utf-8 -*-
"""Caso 3: checklist global de Sage. Un nº de serie que aún no existe en
Odoo se identifica por lo que dice la carpeta de Sage."""

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSageGlobalChecklist(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        warehouse = cls.env['stock.warehouse'].search([('company_id', '=', cls.env.company.id)], limit=1)
        cls.session = cls.env['rms.stock.count.session'].create({'location_id': warehouse.lot_stock_id.id})
        Operator = cls.env['rms.stock.count.operator']
        cls.operator = Operator.browse(Operator.scanner_join(cls.session.id, 'Global')['operator']['id'])
        cls.Scan = cls.env['rms.stock.count.scan']
        cls.brand = cls.env['product.category'].create({'name': 'RMSTEST Global Brand'})
        Product = cls.env['product.product']
        cls.galaxy = Product.create({'name': 'GLOBAL GALAXY', 'categ_id': cls.brand.id,
                                     'is_storable': True, 'tracking': 'serial'})
        cls.leopard = Product.create({'name': 'GLOBAL LEOPARD', 'categ_id': cls.brand.id,
                                      'is_storable': True, 'tracking': 'serial'})
        cls.cable = Product.create({'name': 'GLOBAL CABLE', 'categ_id': cls.brand.id,
                                    'is_storable': True, 'tracking': 'none'})
        cls.snapshot = cls.env['rms.sage.snapshot'].create({
            'name': 'Global test', 'brand_categ_id': cls.brand.id, 'sage_company_code': '02',
        })

    def _sage(self, serial, product=False, article='GLOBAL-ART', warehouse='A.7', state='nuevo'):
        return self.env['rms.sage.stock.line'].create({
            'snapshot_id': self.snapshot.id, 'is_current': True, 'warehouse_code': warehouse,
            'article_code': article, 'model_code': article, 'serial': serial,
            'product_id': product.id if product else False, 'state': state,
            'match_state': 'ok' if product else 'sin_producto',
        })

    def _scan(self, code):
        return self.Scan.scanner_register(self.operator.id, code)

    def test_serial_only_in_sage_takes_its_product(self):
        self._sage('GLX-0001', self.galaxy)
        self.operator.current_product_id = False
        result = self._scan('GLX-0001')
        scan = self.Scan.browse(result['scan']['id'])
        self.assertEqual(scan.scan_type, 'serial')
        self.assertEqual(scan.product_id, self.galaxy)
        self.assertEqual(scan.lot_name, 'GLX-0001')
        self.assertTrue(scan.is_new_lot)
        self.assertIn('según Sage', scan.message)

    def test_normalized_match(self):
        self._sage('0011650', self.galaxy)
        self.operator.current_product_id = False
        scan = self.Scan.browse(self._scan(' 0011650 ')['scan']['id'])
        self.assertEqual(scan.product_id, self.galaxy)

    def test_serial_in_several_products_needs_product(self):
        self._sage('DUP-1', self.galaxy)
        self._sage('DUP-1', self.leopard, article='GLOBAL-ART2')
        self.operator.current_product_id = False
        scan = self.Scan.browse(self._scan('DUP-1')['scan']['id'])
        self.assertEqual(scan.scan_type, 'unknown')
        self.assertIn('varios productos', scan.message)

    def test_current_product_resolves_ambiguity(self):
        self._sage('DUP-2', self.galaxy)
        self._sage('DUP-2', self.leopard, article='GLOBAL-ART2')
        self.operator.current_product_id = self.leopard
        scan = self.Scan.browse(self._scan('DUP-2')['scan']['id'])
        self.assertEqual(scan.scan_type, 'serial')
        self.assertEqual(scan.product_id, self.leopard)

    def test_sage_article_without_product(self):
        self._sage('NOPROD-1', False, article='GLOBAL-UNKNOWN-ART')
        self.operator.current_product_id = False
        scan = self.Scan.browse(self._scan('NOPROD-1')['scan']['id'])
        self.assertEqual(scan.scan_type, 'unknown')
        self.assertIn('GLOBAL-UNKNOWN-ART', scan.message)
        self.assertIn('Artículos sin producto', scan.message)

    def test_untracked_product_is_flagged(self):
        self._sage('CABLE-1', self.cable)
        self.operator.current_product_id = False
        scan = self.Scan.browse(self._scan('CABLE-1')['scan']['id'])
        self.assertEqual(scan.scan_type, 'unknown')
        self.assertIn('no se sigue por nº de serie', scan.message)

    def test_scanner_progress_counts_the_linked_sage_warehouse(self):
        wh = self.env['rms.sage.warehouse'].create({
            'code': 'TPRG', 'name': 'Prueba progreso', 'sage_company_code': '02',
            'location_id': self.session.location_id.id})
        counted = self._sage('PRG-1', self.galaxy)
        pending = self._sage('PRG-2', self.galaxy)
        demo = self._sage('PRG-3', self.galaxy, state='demo')
        deposit = self._sage('PRG-4', self.galaxy)
        negative = self._sage('PRG-5', self.galaxy)
        (counted | pending | demo | deposit | negative).write({'sage_warehouse_id': wh.id})
        deposit.in_deposit = True
        negative.quantity = -1
        self._sage('PRG-6', self.galaxy, warehouse='OTRO')  # otro almacén: no cuenta
        self.operator.current_product_id = False
        self.operator.scanner_set_state(self.env.ref('rms_product_state.state_new').id)
        self._scan('PRG-1')            # verde
        self._scan('PRG-3')            # ámbar: Sage dice Demo
        self.operator.current_product_id = False
        self._scan('NOT-IN-SAGE-PRG')  # pendiente (sin producto)
        self.operator.current_product_id = self.galaxy
        self._scan('NEW-PRG-9')        # nº de serie nuevo: no está en Sage
        progress = self.operator.scanner_progress()
        self.assertTrue(progress['has_sage'])
        self.assertIn('TPRG', progress['site'])
        self.assertEqual((progress['total'], progress['counted'], progress['pending']), (3, 2, 1))
        self.assertEqual(progress['not_in_sage'], 1)
        self.assertEqual(progress['review'], 2)
        self.assertEqual(progress['mine'], self.operator.scan_count)

    def test_apostrophe_from_english_keyboard_is_a_hyphen(self):
        self._sage('EASN0-0005', self.galaxy)
        self.operator.current_product_id = False
        scan = self.Scan.browse(self._scan("EASN0'0005")['scan']['id'])
        self.assertEqual(scan.scan_type, 'serial')
        self.assertEqual(scan.lot_name, 'EASN0-0005')

    def test_demo_written_before_or_after_the_model(self):
        from ..models.sage_expected import sage_article_parts
        self.assertEqual(sage_article_parts('0923700102-DEMO'), ('0923700102', 'Demo'))
        self.assertEqual(sage_article_parts('DEMO-0928700117'), ('0928700117', 'Demo'))
        self.assertEqual(sage_article_parts('D-0923700102'), ('0923700102', 'Demo'))
        self.assertEqual(sage_article_parts('0923700102'), ('0923700102', 'Nuevo'))
        self.assertEqual(sage_article_parts('DEMOLEDOR-1'), ('DEMOLEDOR-1', 'Nuevo'))

    def test_unknown_product_barcode_never_becomes_serial(self):
        # Caja Sound Devices: nº de serie (en Sage) y UPC del producto (no en Odoo).
        self._sage('AA0625052008', self.galaxy)
        self.operator.current_product_id = False
        first = self.Scan.browse(self._scan('AA0625052008')['scan']['id'])
        self.assertEqual(first.product_id, self.galaxy)
        self.assertEqual(self.operator.current_product_id, self.galaxy)
        upc = self.Scan.browse(self._scan('850032705400')['scan']['id'])
        self.assertTrue(upc.ignored)
        self.assertFalse(upc.is_new_lot)
        self.assertFalse(upc.lot_name)
        self.assertIn('no es un nº de serie', upc.message)
        # Sin producto actual: pendiente, pero tampoco como nº de serie.
        self.operator.current_product_id = False
        alone = self.Scan.browse(self._scan('850032705400')['scan']['id'])
        self.assertEqual(alone.scan_type, 'unknown')
        self.assertFalse(alone.lot_name)
        # Un nº de serie numérico que SÍ está en Sage sigue contando aunque parezca un UPC.
        self._sage('850032705400', self.galaxy, article='GLOBAL-NUM')
        numeric = self.Scan.browse(self._scan('850032705400')['scan']['id'])
        self.assertEqual(numeric.scan_type, 'serial')
        self.assertEqual(numeric.lot_name, '850032705400')

    def test_serial_not_in_sage_stays_unknown(self):
        self.operator.current_product_id = False
        scan = self.Scan.browse(self._scan('NOT-IN-SAGE-9')['scan']['id'])
        self.assertEqual(scan.scan_type, 'unknown')

    def test_global_verdict_green_anywhere_with_details(self):
        self._sage('VER-1', self.galaxy, article='0907600102', warehouse='AL1', state='2mano')
        verdict = self.Scan._sage_verdict(['VER-1'], self.session, self.galaxy, ['second_hand'])[0]
        self.assertEqual(verdict['v'], 'ok')
        self.assertEqual(verdict['h'][0][0], '02')       # empresa Sage
        self.assertEqual(verdict['h'][0][1], 'AL1')      # almacén
        self.assertEqual(verdict['h'][0][3], '2Mano')    # estado Sage
        self.assertEqual(verdict['h'][0][4], '0907600102')  # modelo

    def test_change_state_of_a_reading_afterwards(self):
        # Se escanea todo seguido como Nuevo y luego se corrige la línea a Demo.
        self._sage('ROW-1', self.galaxy, state='demo')
        self.operator.current_product_id = False
        self.operator.scanner_set_state(self.env.ref('rms_product_state.state_new').id)
        result = self._scan('ROW-1')
        self.assertEqual(result['scan']['sage']['v'], 'est')
        scan = self.Scan.browse(result['scan']['id'])
        demo = self.env.ref('rms_product_state.state_demo')
        payload = scan.scanner_change_state(demo.id)
        self.assertEqual(scan.product_state_id, demo)
        self.assertEqual(payload['product_state_id'], demo.id)
        self.assertEqual(payload['sage']['v'], 'ok')
        # El estado activo para las siguientes lecturas no cambia.
        self.assertEqual(self.operator.current_state_id, self.env.ref('rms_product_state.state_new'))
        with self.assertRaises(UserError):
            scan.scanner_change_state(self.env.ref('rms_product_state.state_new').id + 99999)

    def test_negative_sage_line_is_not_a_duplicate(self):
        # Galileo 23341574: +1 Demo en A.7 y -1 Nuevo en AL1 (salió con otro artículo).
        self._sage('NEG-1', self.galaxy, article='0923700102-DEMO', warehouse='A.7', state='demo')
        negative = self._sage('NEG-1', self.galaxy, article='0923700102', warehouse='AL1', state='nuevo')
        negative.quantity = -1
        self.env['rms.sage.stock.line']._update_duplicates()
        self.assertEqual(negative.dup_count, 0)
        verdict = self.Scan._sage_verdict(['NEG-1'], self.session, self.galaxy, ['new'])[0]
        self.assertEqual(verdict['v'], 'est')
        self.assertEqual([h[1] for h in verdict['h']], ['A.7'])
        self.assertFalse(self.env['rms.sage.checklist'].search([('serial_normalized', '=', 'NEG1'), ('warehouse_code', '=', 'AL1')])
                         if 'serial_normalized' in self.env['rms.sage.checklist']._fields else False)

    def test_global_verdict_state_mismatch_is_amber(self):
        self._sage('VER-2', self.galaxy, state='demo')
        verdict = self.Scan._sage_verdict(['VER-2'], self.session, self.galaxy, ['new'])[0]
        self.assertEqual(verdict['v'], 'est')
        self.assertEqual(verdict['st'], 'Nuevo')
        exdemo = self.Scan._sage_verdict(['VER-2'], self.session, self.galaxy, ['ex_demo'])[0]
        self.assertEqual(exdemo['v'], 'est')  # Ex-Demo no existe en Sage

    def test_global_verdict_duplicate_and_absent(self):
        self._sage('VER-3', self.galaxy, warehouse='AL1')
        self._sage('VER-3', self.galaxy, warehouse='A.7')
        verdicts = self.Scan._sage_verdict(['VER-3', 'NOPE-3'], self.session, [self.galaxy.id, False], ['new', 'new'])
        self.assertEqual([v['v'] for v in verdicts], ['dup', 'none'])

    def test_scan_payload_carries_global_verdict(self):
        self._sage('VER-4', self.galaxy)
        self.operator.current_product_id = False
        result = self._scan('VER-4')
        self.assertEqual(result['sage']['v'], 'ok')

    def test_rescan_with_corrected_state_updates_reading(self):
        self._sage('FIX-1', self.galaxy, state='2mano')
        self.operator.current_product_id = False
        new = self.env.ref('rms_product_state.state_new')
        used = self.env.ref('rms_product_state.state_second_hand')
        self.operator.scanner_set_state(new.id)
        first = self._scan('FIX-1')
        self.assertEqual(first['sage']['v'], 'est')
        self.operator.scanner_set_state(used.id)
        second = self._scan('FIX-1')
        self.assertEqual(second['status'], 'ok')
        self.assertEqual(second['scan']['id'], first['scan']['id'])
        self.assertEqual(self.Scan.browse(first['scan']['id']).product_state_id, used)
        self.assertEqual(second['sage']['v'], 'ok')
        third = self._scan('FIX-1')
        self.assertEqual(third['status'], 'duplicate')

    def _prepare(self, lines):
        action = lines.action_prepare_products()
        return self.env['rms.sage.product.prepare'].with_context(action['context']).create({})

    def test_prepare_creates_products_grouping_state_variants(self):
        new = self._sage('NEWP-1', False, article='0912345678')
        new.article_name = 'LINA - Line array compacto'
        demo = self._sage('NEWP-2', False, article='D-0912345678', state='demo')
        demo.model_code = '0912345678'
        new.model_code = '0912345678'
        wizard = self._prepare(new | demo)
        self.assertIn('se crearán como productos nuevos: 1', wizard.preview)
        wizard.action_create_products()
        product = self.env['product.template'].search([('default_code', '=', '0912345678')])
        self.assertEqual(len(product), 1)
        self.assertEqual(product.name, 'LINA - Line array compacto')
        self.assertEqual(product.tracking, 'serial')
        self.assertTrue(product.is_storable)
        self.assertEqual(product.categ_id, self.brand)
        self.assertEqual((new | demo).mapped('product_id.product_tmpl_id'), product)
        self.assertEqual(set((new | demo).mapped('match_state')), {'ok'})
        # Ya se reconoce con la pistola
        self.operator.current_product_id = False
        scan = self.Scan.browse(self._scan('NEWP-2')['scan']['id'])
        self.assertEqual(scan.scan_type, 'serial')
        self.assertEqual(scan.product_id.product_tmpl_id, product)

    def test_prepare_assigns_existing_reference(self):
        self.galaxy.default_code = 'GLX-REF-1'
        line = self._sage('ASG-1', False, article='GLX-REF-1')
        self._prepare(line).action_create_products()
        self.assertEqual(line.product_id, self.galaxy)
        self.assertEqual(self.env['product.template'].search_count([('default_code', '=', 'GLX-REF-1')]), 1)

    def test_prepare_uses_existing_alias_before_creating(self):
        # MQ-RACK (Sage) ya enlazado a X-MQ-RACK (Odoo): su demo no crea otro producto.
        self.galaxy.default_code = 'X-ALIAS-RACK'
        self.env['rms.sage.article.map'].create({'article_code': 'ALIASRACK',
                                                 'product_tmpl_id': self.galaxy.product_tmpl_id.id})
        demo = self._sage('ALIAS-1', False, article='D-ALIAS-RACK', state='demo')
        demo.model_code = 'ALIAS-RACK'
        self._prepare(demo).action_create_products()
        self.assertEqual(demo.product_id, self.galaxy)
        self.assertFalse(self.env['product.template'].search([('default_code', '=', 'ALIAS-RACK')]))

    def test_enable_serial_tracking_skips_products_with_stock(self):
        plain = self.env['product.product'].create({'name': 'GLOBAL PLAIN', 'categ_id': self.brand.id,
                                                    'is_storable': True, 'tracking': 'none'})
        stocked = self.env['product.product'].create({'name': 'GLOBAL STOCKED', 'categ_id': self.brand.id,
                                                      'is_storable': True, 'tracking': 'none'})
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1)
        self.env['stock.quant']._update_available_quantity(stocked, warehouse.lot_stock_id, 2)
        lines = self._sage('TRK-1', plain) | self._sage('TRK-2', stocked)
        self._prepare(lines).action_enable_serial_tracking()
        self.assertEqual(plain.tracking, 'serial')
        self.assertEqual(stocked.tracking, 'none')

    def test_import_keeps_article_name(self):
        import base64
        raw = ('Almacén;Artículo;Nombre artículo;Lotes;Unidades\n'
               'AL1;NAMETEST-ART;Caja autoamplificada de prueba;;1\n'
               ';;;NAMESER-1;1\n').encode()
        self.env['rms.stock.count.sage.import'].create({
            'scope': 'brand', 'brand_categ_id': self.brand.id, 'filename': 'nombres.csv',
            'file_data': base64.b64encode(raw), 'sage_company_code': '03',
        }).action_import()
        line = self.env['rms.sage.stock.line'].search([('serial', '=', 'NAMESER-1')])
        self.assertEqual(line.article_name, 'Caja autoamplificada de prueba')

    def _second_operator(self):
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1)
        other = self.env['rms.stock.count.session'].create({'location_id': warehouse.lot_stock_id.id})
        Operator = self.env['rms.stock.count.operator']
        return other, Operator.browse(Operator.scanner_join(other.id, 'Otro día')['operator']['id'])

    def test_checklist_view_counts_across_sessions(self):
        read = self._sage('CHK-1', self.galaxy, state='nuevo')
        unread = self._sage('CHK-2', self.galaxy)
        wrong_state = self._sage('CHK-3', self.galaxy, state='demo')
        self.operator.current_product_id = False
        self.operator.scanner_set_state(self.env.ref('rms_product_state.state_new').id)
        self._scan('CHK-1')
        self._scan('CHK-3')
        other, operator2 = self._second_operator()
        second = self.Scan.scanner_register(operator2.id, 'CHK-1')
        self.assertEqual(second['scan']['also_in'], self.session.name)
        self.env.flush_all()
        Checklist = self.env['rms.sage.checklist']
        rows = {row.sage_line_id: row for row in Checklist.search(
            [('sage_line_id', 'in', (read | unread | wrong_state).ids)])}
        self.assertTrue(rows[read].counted)
        self.assertEqual(rows[read].session_count, 2)
        self.assertTrue(rows[read].multi_session)
        self.assertFalse(rows[read].state_mismatch)
        self.assertFalse(rows[unread].counted)
        self.assertTrue(rows[wrong_state].state_mismatch)
        # Un recuento cancelado deja de contar.
        other.state = 'cancel'
        self.env.flush_all()
        self.env.invalidate_all()
        self.assertEqual(Checklist.search([('sage_line_id', '=', read.id)]).session_count, 1)

    def test_checklist_extra_lists_serials_not_in_sage(self):
        self._sage('EXT-IN', self.galaxy)
        self.operator.current_product_id = self.galaxy
        self._scan('EXT-IN')
        self._scan('EXT-NOT-IN-SAGE')
        self.env.flush_all()
        extra = self.env['rms.sage.checklist.extra'].search([('session_id', '=', self.session.id)])
        self.assertEqual(extra.mapped('lot_name'), ['EXT-NOT-IN-SAGE'])

    def test_atlas_sn_prefix_matches_both_ways(self):
        self._sage('SNDH700912472001557', self.galaxy)
        self._sage('DH800000000000001', self.leopard, article='GLOBAL-ART2')
        self.operator.current_product_id = False
        with_sn = self.Scan.browse(self._scan('DH700912472001557')['scan']['id'])
        self.assertEqual(with_sn.product_id, self.galaxy)
        without_sn = self.Scan.browse(self._scan('S/N: DH800000000000001')['scan']['id'])
        self.assertEqual(without_sn.product_id, self.leopard)
        verdict = self.Scan._sage_verdict(['DH700912472001557'], self.session, self.galaxy, ['new'])[0]
        self.assertEqual(verdict['v'], 'ok')

    def test_replaced_snapshot_lines_are_ignored(self):
        line = self._sage('OLD-1', self.galaxy)
        line.is_current = False
        self.operator.current_product_id = False
        scan = self.Scan.browse(self._scan('OLD-1')['scan']['id'])
        self.assertEqual(scan.scan_type, 'unknown')

    # --- Flujo: etiqueta desde la lectura, "Buscar en Sage", nombres Sage/Odoo ---

    def test_print_label_from_reading_links_lot_without_new_scan(self):
        self._sage('LBLR-1', self.galaxy, article='GAL-ART', state='nuevo')
        self.operator.current_product_id = False
        scan = self.Scan.browse(self._scan('LBLR-1')['scan']['id'])
        before = self.Scan.search_count([('session_id', '=', self.session.id)])
        action = scan.scanner_print_label()
        lot = self.env['stock.lot'].search([('product_id', '=', self.galaxy.id), ('name', '=', 'LBLR-1')])
        self.assertEqual(len(lot), 1)
        self.assertEqual(scan.lot_id, lot)
        self.assertFalse(scan.is_new_lot)
        self.assertTrue(lot.rms_replacement_label)
        self.assertEqual(action['type'], 'ir.actions.act_url')
        self.assertIn('/report/pdf/rms_stock_lot_label_print.report_lot_label_10x5_document/%d?' % lot.id, action['url'])
        # Reimprimir: mismo lote, ninguna lectura más.
        scan.scanner_print_label()
        self.assertEqual(self.env['stock.lot'].search_count([('product_id', '=', self.galaxy.id), ('name', '=', 'LBLR-1')]), 1)
        self.assertEqual(self.Scan.search_count([('session_id', '=', self.session.id)]), before)

    def test_reading_payload_carries_sage_article_and_name(self):
        line = self._sage('NAME-1', self.galaxy, article='0923700102')
        line.article_name = 'GALILEO GALAXY 408 (Sage)'
        self.operator.current_product_id = False
        payload = self._scan('NAME-1')['scan']
        self.assertEqual(payload['sage']['sa'], '0923700102')
        self.assertEqual(payload['sage']['sn'], 'GALILEO GALAXY 408 (Sage)')

    def test_sage_search_lists_only_pending_and_filters(self):
        line1 = self._sage('SRCH-0001', self.galaxy, article='MESA-SD12')
        line1.article_name = 'Consola SD12 en flycase'
        self._sage('SRCH-0002', self.galaxy, article='MESA-SD12')
        negative = self._sage('SRCH-0003', self.galaxy, article='MESA-SD12')
        negative.quantity = -1
        self.operator.current_product_id = False
        self._scan('SRCH-0001')
        found = self.operator.scanner_sage_search('sd12')
        serials = [r['serial'] for r in found]
        self.assertIn('SRCH-0002', serials)
        self.assertNotIn('SRCH-0001', serials)   # ya contado
        self.assertNotIn('SRCH-0003', serials)   # negativo en Sage
        self.assertEqual([r['serial'] for r in self.operator.scanner_sage_search('0002')], ['SRCH-0002'])
        self.assertEqual(self.operator.scanner_sage_search('flycase'), [])  # el contado no vuelve a salir
        self.assertFalse(self.operator.scanner_sage_search('NOEXISTEZZZ'))

    def test_sage_print_and_count_creates_green_reading_with_sage_state(self):
        line = self._sage('PAC-1', self.galaxy, article='MESA-PAC', state='demo')
        self.operator.scanner_set_state(self.env.ref('rms_product_state.state_new').id)
        result = self.operator.scanner_sage_print_and_count(line.id)
        scan = self.Scan.browse(result['scan']['id'])
        self.assertEqual(scan.scan_type, 'serial')
        self.assertEqual(scan.product_id, self.galaxy)
        self.assertEqual(scan.product_state_id, self.env.ref('rms_product_state.state_demo'))
        self.assertEqual(result['scan']['sage']['v'], 'ok')
        self.assertTrue(scan.lot_id)
        self.assertEqual(result['action']['type'], 'ir.actions.act_url')
        # Otra vez el mismo: no cuenta doble.
        again = self.operator.scanner_sage_print_and_count(line.id)
        self.assertEqual(again['scan']['id'], scan.id)
        self.assertEqual(self.Scan.search_count([('session_id', '=', self.session.id), ('lot_name', '=', 'PAC-1')]), 1)
        self.assertFalse(self.operator.scanner_sage_search('MESA-PAC'))
