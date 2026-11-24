# -*- coding: utf-8 -*-
"""Escáner del recuento: "coincidencia probable" con Sage (nº de serie mal
escrito en Sage) y crear el producto desde el catálogo de Sage."""

import base64
import io
import logging
import time

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, new_test_user, tagged

from ..models.stock_count_match import similar_kind, similar_serials

_logger = logging.getLogger(__name__)

REAL_LABEL = 'SNDQ703190152400014'    # lo que dice la etiqueta del FC-8ST
REAL_SAGE = 'SNDQ7031901524040014'    # lo que alguien tecleó en Sage (un 4 de más)
# La regla de AtlasIED quita el "SN" del código de barras: ese es el nº de serie leído.
REAL_READ = 'DQ703190152400014'


@tagged('post_install', '-at_install')
class TestScannerMatch(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.c1 = cls.env.company
        Warehouse = cls.env['stock.warehouse']
        cls.wh = {code: Warehouse.create({'name': 'MATCH %s' % code, 'code': code, 'company_id': cls.c1.id})
                  for code in ('RMS7', 'RMS1')}
        Category = cls.env['product.category']
        cls.brand = Category.create({'name': 'MATCHTEST Atlas'})
        Product = cls.env['product.product']

        def product(name, ref, tracking='serial'):
            return Product.create({'name': name, 'default_code': ref, 'categ_id': cls.brand.id,
                                   'is_storable': True, 'tracking': tracking})

        cls.fc = product('MATCHT FC-8ST', 'MT-FC8ST')
        cls.other = product('MATCHT OTRO', 'MT-OTRO')
        cls.snapshot = cls.env['rms.sage.snapshot'].create({
            'name': 'Match 01', 'brand_categ_id': cls.brand.id, 'sage_company_code': '01',
            'company_id': cls.c1.id})
        line = cls._line
        cls.l_real = line(cls.fc, REAL_SAGE)                 # carácter de más en Sage
        cls.l_less = line(cls.fc, 'KX12345')                 # a Sage le falta un carácter
        cls.l_changed = line(cls.fc, 'QZ77A1234')            # un carácter cambiado
        cls.l_confused = line(cls.fc, 'TRO0PER01')           # O/0 (dos confusiones)
        cls.l_swapped = line(cls.fc, 'MN4567812')            # dos vecinos intercambiados
        cls.l_short = line(cls.fc, 'AB123')                  # corto: nunca se propone
        cls.l_multi1 = line(cls.fc, 'DUPX10001')
        cls.l_multi2 = line(cls.fc, 'DUPX10002')
        cls.env['rms.sage.warehouse']._setup_default_links()
        cls.Session = cls.env['rms.stock.count.session']
        cls.Operator = cls.env['rms.stock.count.operator']
        cls.Scan = cls.env['rms.stock.count.scan']
        cls.session = cls.Session.create({'location_id': cls.wh['RMS7'].lot_stock_id.id})
        cls.operator = cls._join(cls.session, 'Ana')
        cls.states = {state['code']: state['id'] for state in cls.operator.scanner_state()['product_states']}

    @classmethod
    def _line(cls, product, serial, warehouse='A.7', quantity=1):
        return cls.env['rms.sage.stock.line'].sudo().create({
            'snapshot_id': cls.snapshot.id, 'is_current': True,
            'warehouse_code': warehouse, 'article_code': product.default_code, 'model_code': product.default_code,
            'article_name': product.name, 'serial': serial, 'quantity': quantity, 'product_id': product.id,
            'state': 'nuevo', 'match_state': 'ok'})

    @classmethod
    def _join(cls, session, name):
        return cls.Operator.browse(cls.Operator.scanner_join(session.id, name)['operator']['id'])

    def _scan(self, code, operator=None):
        operator = operator or self.operator
        return self.Scan.scanner_register(operator.id, code, product_state_id=self.states['new'])

    def _suggested(self, code, operator=None):
        result = self._scan(code, operator)
        self.assertEqual(result['scan']['match'] and result['scan']['match']['state'], 'suggested', result['message'])
        return result, self.Scan.browse(result['scan']['id'])

    # ------------------------------------------------------------------
    # Qué se parece y qué no
    # ------------------------------------------------------------------

    def test_similar_serials(self):
        self.assertTrue(similar_serials('DQ703190152400014', 'DQ7031901524040014'))   # de más
        self.assertTrue(similar_serials('KX123945', 'KX12345'))                       # de menos
        self.assertTrue(similar_serials('QZ77B1234', 'QZ77A1234'))                    # cambiado
        self.assertTrue(similar_serials('MN4576812', 'MN4567812'))                    # vecinos intercambiados
        for a, b in (('O', '0'), ('Q', '0'), ('I', '1'), ('L', '1'), ('S', '5'), ('B', '8'), ('Z', '2')):
            self.assertTrue(similar_serials('XX%sYY%sKK' % (a, a), 'XX%sYY%sKK' % (b, b)), (a, b))
        self.assertFalse(similar_serials('QZ77B1234', 'QZ77A1235'))                   # dos cambios
        self.assertFalse(similar_serials('MN4576812', 'MN4657812'))
        self.assertFalse(similar_serials('ABCDEFGH', 'ABCDEF'))
        self.assertEqual(similar_kind('DQ703190152400014', 'DQ7031901524040014'), 'extra')
        self.assertEqual(similar_kind('KX123945', 'KX12345'), 'missing')
        self.assertEqual(similar_kind('QZ77B1234', 'QZ77A1234'), 'changed')
        self.assertEqual(similar_kind('MN4576812', 'MN4567812'), 'swapped')
        self.assertEqual(similar_kind('TR00PERO1', 'TRO0PER01'), 'confused')

    def test_typo_goes_before_consecutive_serials(self):
        """Caso real completo: los FC-8ST son correlativos, así que los vecinos
        sin leer también "se parecen". La errata de tecleo va la primera y cada
        candidata dice en qué se diferencia."""
        self._line(self.fc, 'SNDQ703190152400017')
        self._line(self.fc, 'SNDQ703190152400018')
        self.env['rms.sage.warehouse']._relink_lines()
        result, scan = self._suggested(REAL_LABEL)
        candidates = result['scan']['match']['candidates']
        self.assertEqual([c['serial'] for c in candidates],
                         [REAL_SAGE, 'SNDQ703190152400017', 'SNDQ703190152400018'])
        self.assertEqual(candidates[0]['why'], 'en Sage sobra un carácter')
        self.assertEqual(candidates[1]['why'], 'cambia un carácter')
        # Leídos los vecinos, queda una sola candidata.
        scan.scanner_match_reject()
        scan.unlink()
        self.assertEqual(self._scan('SNDQ703190152400017')['status'], 'ok')
        self.assertEqual(self._scan('SNDQ703190152400018')['status'], 'ok')

    def test_real_case_one_extra_character_in_sage(self):
        """FC-8ST de Madrid: etiqueta SNDQ703190152400014, Sage SNDQ7031901524040014."""
        result, scan = self._suggested(REAL_LABEL)
        self.assertEqual(result['status'], 'unknown')          # no cuenta todavía
        self.assertEqual(result['sage']['v'], 'prob')
        self.assertEqual(result['scan']['sage']['v'], 'prob')
        match = result['scan']['match']
        self.assertEqual([c['serial'] for c in match['candidates']], [REAL_SAGE])
        self.assertEqual(result['scan']['product_name'], self.fc.display_name)
        self.assertEqual(result['message'],
                         'Se parece a %s de Sage (%s). ¿Es este?' % (REAL_SAGE, self.fc.display_name))
        self.assertEqual(scan.sage_match_line_id, self.l_real)
        self.assertEqual(scan.lot_name, REAL_READ)
        # Sin confirmar no cuenta como leída: sigue en "faltan" y a revisar.
        progress = self.operator.scanner_progress()
        self.assertEqual(progress['counted'], 0)
        self.assertEqual(progress['review'], 1)
        # Sale también al recargar el escáner.
        history = self.Scan.scanner_history(self.operator.id)
        self.assertEqual(history[0]['sage']['v'], 'prob')
        self.assertEqual(history[0]['match']['state'], 'suggested')

    def test_each_kind_of_typo_is_suggested(self):
        for label, line in (('KX123945', self.l_less), ('QZ77B1234', self.l_changed),
                            ('TR00PERO1', self.l_confused), ('MN4576812', self.l_swapped)):
            _result, scan = self._suggested(label)
            self.assertEqual(scan.sage_match_line_id, line, label)
            self.assertEqual(scan.sage_match_key, line.serial_normalized)

    def test_exact_and_short_serials_never_suggest(self):
        exact = self._scan(REAL_SAGE)
        self.assertEqual(exact['status'], 'ok')
        self.assertFalse(exact['scan']['match'])
        short = self._scan('AB124')                            # 5 caracteres: no se propone nada
        self.assertFalse(short['scan']['match'])
        self.assertEqual(short['status'], 'unknown')
        nothing = self._scan('ZZZ-NADA-99887')                 # no se parece a nada
        self.assertFalse(nothing['scan']['match'])

    def test_already_read_line_is_not_suggested(self):
        other = self._join(self.session, 'Luis')
        self.assertEqual(self._scan(REAL_SAGE, other)['status'], 'ok')    # alguien leyó el de Sage
        result = self._scan(REAL_LABEL)
        self.assertFalse(result['scan']['match'])
        self.assertEqual(result['scan']['type'], 'unknown')
        self.assertIn('elige el producto', result['message'])

    def test_several_candidates(self):
        result, scan = self._suggested('DUPX10003')
        self.assertEqual({c['serial'] for c in result['scan']['match']['candidates']}, {'DUPX10001', 'DUPX10002'})
        self.assertFalse(scan.product_id)
        self.assertFalse(scan.sage_match_key)
        with self.assertRaises(UserError):
            scan.scanner_match_confirm()                       # hay que elegir cuál
        with self.assertRaises(UserError):
            scan.scanner_match_confirm('NOESTA')
        done = scan.scanner_match_confirm(self.l_multi2.serial_normalized, self.operator.id)
        self.assertEqual(done['scan']['type'], 'serial')
        self.assertEqual(scan.sage_match_line_id, self.l_multi2)
        # "Ninguna": descarta todas.
        _result, again = self._suggested('DUPX10004')
        self.assertEqual([c['serial'] for c in again.sage_match_candidates], ['DUPX10001'])
        again.scanner_match_reject()
        self.assertEqual(again.sage_match_state, 'rejected')
        self.assertEqual(again.sage_match_rejected, ['DUPX10001'])

    def test_same_label_twice_asks_once(self):
        first, scan = self._suggested(REAL_LABEL)
        second = self._scan(REAL_LABEL)
        self.assertEqual(second['status'], 'duplicate')
        self.assertEqual(second['scan']['id'], first['scan']['id'])
        self.assertEqual(self.Scan.search_count([('operator_id', '=', self.operator.id)]), 1)

    # ------------------------------------------------------------------
    # "Sí, es este"
    # ------------------------------------------------------------------

    def _list_row(self, line):
        data = self.operator.scanner_list_serials(self.brand.id, 'p%d' % self.fc.id)
        return next(row for row in data['rows'] if row['id'] == line.id)

    def test_confirm_counts_everywhere(self):
        _result, scan = self._suggested(REAL_LABEL)
        checklist = self.env['rms.sage.checklist'].search([('sage_line_id', '=', self.l_real.id)])
        self.assertFalse(checklist.counted)
        row = self._list_row(self.l_real)
        self.assertEqual(row['k'], 'todo')
        self.assertEqual(row['sug'], {'id': scan.id, 'serial': REAL_READ})   # "¿es <leído>?" en la Lista
        extras = self.env['rms.sage.checklist.extra']
        self.assertTrue(extras.search([('scan_id', '=', scan.id)]))

        done = scan.scanner_match_confirm(False, self.operator.id)
        self.assertEqual(done['status'], 'confirmed')
        payload = done['scan']
        self.assertEqual(payload['type'], 'serial')
        self.assertEqual(payload['lot_name'], REAL_READ)      # manda lo leído en la etiqueta
        self.assertEqual(payload['sage']['v'], 'ok')
        self.assertEqual(payload['match']['state'], 'confirmed')
        self.assertEqual(payload['match']['serial'], REAL_SAGE)
        self.assertEqual(payload['match']['by'], 'Ana')
        self.assertEqual(scan.sage_match_line_id, self.l_real)
        self.assertEqual(scan.sage_match_user_id, self.env.user)
        self.assertEqual(scan.sage_match_operator_id, self.operator)
        self.assertTrue(scan.sage_match_date)
        self.assertEqual(scan.product_id, self.fc)
        self.assertEqual(scan.quantity, 1.0)
        self.assertEqual(scan.serial_normalized, REAL_READ)

        progress = self.operator.scanner_progress()
        self.assertEqual(progress['counted'], 1)
        self.assertEqual(progress['not_in_sage'], 0)
        self.assertEqual(progress['review'], 0)
        self.env.invalidate_all()
        checklist = self.env['rms.sage.checklist'].search([('sage_line_id', '=', self.l_real.id)])
        self.assertTrue(checklist.counted)
        self.assertTrue(checklist.matched)
        self.assertEqual(checklist.matched_serial, REAL_READ)
        self.assertEqual(checklist.pending_qty, 0)
        self.assertEqual(self.env['rms.sage.checklist'].search([('matched', '=', True)]), checklist)
        self.assertFalse(extras.search([('scan_id', '=', scan.id)]))          # ya no es un alta
        self.assertFalse(self.operator.scanner_list_extra()['rows'])
        row = self._list_row(self.l_real)
        self.assertEqual(row['k'], 'ok')
        self.assertEqual(row['read_as'], REAL_READ)
        self.assertFalse(row['sug'])
        brands = self.operator.scanner_list_brands()
        self.assertEqual(brands['counted'], 1)
        self.assertEqual(brands['extra_count'], 0)
        # "Buscar en Sage" ya no lo ofrece como pendiente.
        self.assertNotIn(REAL_SAGE, [r['serial'] for r in self.operator.scanner_sage_search('FC8ST')])

        # Idempotente: repetir la confirmación no cambia nada.
        again = scan.scanner_match_confirm(self.l_real.serial_normalized, self.operator.id)
        self.assertEqual(again['status'], 'confirmed')
        self.assertEqual(self.Scan.search_count([('session_id', '=', self.session.id)]), 1)
        # Releer la misma etiqueta: "ya leído", no otra pregunta.
        self.assertEqual(self._scan(REAL_LABEL)['status'], 'duplicate')
        # Otro operario lee la misma etiqueta: hereda el emparejamiento (no vuelve a preguntar).
        other = self._join(self.session, 'Luis')
        inherited = self._scan(REAL_LABEL, other)
        self.assertEqual(inherited['status'], 'ok')
        self.assertEqual(inherited['scan']['match']['state'], 'confirmed')
        self.assertEqual(inherited['sage']['v'], 'ok')
        # Ya confirmada: no se puede descartar.
        with self.assertRaises(UserError):
            scan.scanner_match_reject()

    def test_confirm_from_another_operator_and_peers(self):
        other = self._join(self.session, 'Luis')
        _r1, mine = self._suggested(REAL_LABEL)
        _r2, theirs = self._suggested(REAL_LABEL, other)
        mine.scanner_match_confirm(False, other.id)            # lo confirma quien tiene el equipo delante
        self.assertEqual(mine.sage_match_operator_id, other)
        self.assertEqual(theirs.sage_match_state, 'confirmed')  # la misma etiqueta del compañero también
        self.assertEqual(theirs.scan_type, 'serial')
        self.assertEqual(self.operator.scanner_progress()['counted'], 1)

    def test_confirm_refused_when_line_read_meanwhile(self):
        _result, scan = self._suggested(REAL_LABEL)
        other = self._join(self.session, 'Luis')
        self.assertEqual(self._scan(REAL_SAGE, other)['status'], 'ok')
        with self.assertRaises(UserError):
            scan.scanner_match_confirm(False, self.operator.id)
        self.assertEqual(scan.sage_match_state, 'suggested')

    # ------------------------------------------------------------------
    # "No, es otro"
    # ------------------------------------------------------------------

    def test_reject_behaves_like_before(self):
        _result, scan = self._suggested(REAL_LABEL)
        done = scan.scanner_match_reject(self.operator.id)
        self.assertEqual(done['status'], 'rejected')
        self.assertEqual(done['scan']['type'], 'unknown')
        self.assertFalse(done['scan']['product_name'])
        self.assertEqual(done['scan']['sage']['v'], 'none')
        self.assertIn('elige el producto', scan.message)       # el mensaje de siempre
        self.assertEqual(scan.sage_match_rejected, [self.l_real.serial_normalized])
        self.assertEqual(scan.scanner_match_reject()['status'], 'rejected')   # idempotente
        with self.assertRaises(UserError):
            scan.scanner_match_confirm()
        # El operario elige el producto y vuelve a leer: alta, sin volver a proponer lo descartado.
        self.operator.scanner_set_product(self.other.id)
        again = self._scan(REAL_LABEL)
        self.assertEqual(again['status'], 'ok')
        self.assertFalse(again['scan']['match'])
        self.assertTrue(again['scan']['is_new_lot'])
        self.assertEqual(again['scan']['product_name'], self.other.display_name)
        self.assertEqual(again['sage']['v'], 'none')
        self.assertEqual(self.operator.scanner_progress()['counted'], 0)
        self.assertFalse(self.env['rms.sage.checklist'].search([('sage_line_id', '=', self.l_real.id)]).counted)

    def test_reject_with_chosen_product_becomes_new_serial(self):
        self.operator.scanner_set_product(self.other.id)
        _result, scan = self._suggested(REAL_LABEL)            # con producto elegido también se pregunta
        self.assertEqual(scan.product_id, self.fc)
        done = scan.scanner_match_reject()
        self.assertEqual(done['scan']['type'], 'serial')
        self.assertEqual(scan.product_id, self.other)
        self.assertTrue(scan.is_new_lot)
        self.assertEqual(scan.quantity, 1.0)

    # ------------------------------------------------------------------
    # Prioridades
    # ------------------------------------------------------------------

    def test_priority_site_then_other_sites(self):
        here = self._line(self.fc, 'PRIO-770011')
        away = self._line(self.fc, 'PRIO-770012', warehouse='AL1')         # Madrid
        self.env['rms.sage.warehouse']._relink_lines()
        _result, scan = self._suggested('PRIO-770013')
        self.assertEqual([c['id'] for c in scan.sage_match_candidates], [here.id])     # solo la de la nave
        scan.scanner_match_reject()
        self._scan(here.serial)                                # leída la de la nave…
        _result, scan = self._suggested('PRIO-770014')
        self.assertEqual([c['id'] for c in scan.sage_match_candidates], [away.id])     # …queda la de otra nave

    def test_priority_chosen_product(self):
        mine = self._line(self.other, 'PROD-880011')
        self._line(self.fc, 'PROD-880012')
        _result, both = self._suggested('PROD-880013')
        self.assertEqual(len(both.sage_match_candidates), 2)
        both.scanner_match_reject()
        self.operator.scanner_set_product(self.other.id)
        # Las descartadas para ESA etiqueta no vuelven; otra etiqueta sí pregunta, y manda el producto elegido.
        _result, scan = self._suggested('PROD-880014')
        self.assertEqual([c['id'] for c in scan.sage_match_candidates], [mine.id])

    # ------------------------------------------------------------------
    # Excel de descuadres
    # ------------------------------------------------------------------

    def test_mismatch_excel_sheet(self):
        from openpyxl import load_workbook
        _result, confirmed = self._suggested(REAL_LABEL)
        confirmed.scanner_match_confirm(False, self.operator.id)
        self._suggested('KX123945')                             # se queda por confirmar
        wizard = self.env['rms.sage.mismatch.export'].create({})
        wizard.action_export()
        book = load_workbook(io.BytesIO(base64.b64decode(wizard.file)))
        sheet = book['Nº de serie mal escrito en Sage']
        rows = [[cell.value for cell in row] for row in sheet.iter_rows()]
        self.assertEqual(rows[0][:7], ['Empresa', 'Almacén Sage', 'Artículo Sage', 'Nº de serie en Sage',
                                       'Nº de serie leído en la etiqueta', 'Quién lo confirmó', 'Cuándo'])
        self.assertEqual(rows[1][0], 'RMS')
        self.assertEqual(rows[1][2:6], ['MT-FC8ST', REAL_SAGE, REAL_READ, 'Ana'])
        self.assertTrue(rows[1][6])
        section = next(index for index, row in enumerate(rows) if str(row[0] or '').startswith('POR CONFIRMAR'))
        self.assertEqual(rows[section + 1][3:5], ['KX12345', 'KX123945'])
        self.assertIn('POR CONFIRMAR', rows[section + 1][5])
        cover = {row[0].value: row[1].value for row in book['Resumen'].iter_rows(min_row=6) if row[0].value}
        self.assertEqual(cover['Nº de serie mal escrito en Sage'], 1)
        self.assertEqual(cover['   … por confirmar'], 1)
        self.assertIn('Nº de serie mal escrito en Sage: 1 (por confirmar: 1)', wizard.summary)
        # La línea emparejada ya no sale como "No leídos" ni la lectura como "Altas".
        missing = {row[6].value for row in book['No leídos'].iter_rows(min_row=2)}
        self.assertNotIn(REAL_SAGE, missing)
        self.assertIn('KX12345', missing)
        self.assertNotIn(REAL_READ, {row[6].value for row in book['Altas'].iter_rows(min_row=2)})

    # ------------------------------------------------------------------
    # Rendimiento con un Sage de tamaño real
    # ------------------------------------------------------------------

    def test_performance_10000_sage_lines(self):
        warehouse = self.l_real.sage_warehouse_id
        self.assertTrue(warehouse)
        # 5.000 nº de serie "aleatorios" y 5.000 correlativos (el peor caso: comparten principio).
        self.env.cr.execute("""
            INSERT INTO rms_sage_stock_line (snapshot_id, is_current, company_id, sage_company_code, brand_categ_id,
                                             stock_kind, in_deposit, warehouse_code, sage_warehouse_id, article_code,
                                             article_normalized, model_code, model_normalized, state, serial,
                                             serial_normalized, quantity, product_id, match_state, dup_count)
            SELECT %s, TRUE, %s, '01', %s, 'stock', FALSE, 'A.7', %s, 'MT-FC8ST', 'MTFC8ST', 'MT-FC8ST', 'MTFC8ST',
                   'nuevo', s.serial, s.serial, 1, %s, 'ok', 0
              FROM (SELECT CASE WHEN i %% 2 = 0 THEN 'R' || upper(substr(md5(i::text), 1, 13))
                                ELSE 'PERF8ST' || lpad(i::text, 9, '0') END AS serial
                      FROM generate_series(1, 10000) AS i) s
        """, (self.snapshot.id, self.c1.id, self.brand.id, warehouse.id, self.fc.id))
        self.env.cr.execute("ANALYZE rms_sage_stock_line")
        self.env.invalidate_all()
        find = self.Scan._similar_sage_candidates
        self.assertEqual(len(find(self.operator, 'PERF8ST0000A0777')), 1)     # cambiado
        self.assertEqual(len(find(self.operator, 'PERF8ST00000777')), 5)      # correlativos: muchos, se enseñan 5
        self.assertFalse(find(self.operator, 'NADAQUESEPAREZCA1234'))
        samples = ['PERF8ST0000A%04d' % n for n in range(1001, 1041, 2)] + \
                  ['XR%011dQ' % n for n in range(20)] + [REAL_LABEL] * 5
        start = time.perf_counter()
        for serial in samples:
            find(self.operator, serial)
        average = (time.perf_counter() - start) * 1000 / len(samples)
        # Lectura completa (clasificar + guardar + veredicto) de una que NO está en Sage.
        start = time.perf_counter()
        result = self._scan('PERF8ST0000A5555')
        full = (time.perf_counter() - start) * 1000
        self.assertEqual(result['scan']['match']['state'], 'suggested')
        # Y una que SÍ está: no paga la búsqueda de parecidos.
        start = time.perf_counter()
        self.assertEqual(self._scan('PERF8ST000000777')['status'], 'ok')
        exact = (time.perf_counter() - start) * 1000
        _logger.info("PARECIDOS 10.000 líneas: búsqueda media %.1f ms (%d muestras) · lectura completa no en Sage "
                     "%.1f ms · lectura que sí está %.1f ms", average, len(samples), full, exact)
        self.assertLess(average, 60, "La búsqueda de parecidos debe ir por debajo de 60 ms")


@tagged('post_install', '-at_install')
class TestScannerCatalog(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(cls.env, 'match_manager', groups='stock.group_stock_manager')
        cls.worker = new_test_user(cls.env, 'match_worker', groups='stock.group_stock_user')
        warehouse = cls.env['stock.warehouse'].create({'name': 'CATALOGO RMS7', 'code': 'RMS7'})
        Article = cls.env['rms.sage.article']
        cls.article = Article.create({'code': 'A-AA120', 'name': 'AA120 AMPLIFICADOR MEZCLADOR 120W',
                                      'brand_name': 'CATTEST ATLAS'})
        cls.demo = Article.create({'code': 'D-A-AA120', 'name': 'AA120 DEMO', 'brand_name': 'CATTEST ATLAS'})
        cls.cable = Article.create({'code': 'A-CBL77', 'name': 'CABLE DE PRUEBA 77', 'brand_name': 'CATTEST ATLAS'})
        cls.session = cls.env['rms.stock.count.session'].create({'location_id': warehouse.lot_stock_id.id})
        Operator = cls.env['rms.stock.count.operator']
        cls.operator = Operator.browse(Operator.scanner_join(cls.session.id, 'Resp')['operator']['id'])
        cls.Template = cls.env['product.template'].with_context(active_test=False)

    def _as(self, user):
        return self.operator.with_user(user)

    def test_search_catalog(self):
        for query in ('AA120', 'a-aa120', 'aa 120', 'mezclador 120w', 'A.AA-120'):
            data = self._as(self.worker).scanner_catalog_search(query)
            self.assertEqual([a['code'] for a in data['articles']], ['A-AA120'], query)   # la demo es el mismo modelo
        article = data['articles'][0]
        self.assertEqual(article['model'], 'AA120')
        self.assertEqual(article['status'], 'missing')
        self.assertEqual(article['name'], 'AA120 AMPLIFICADOR MEZCLADOR 120W')
        self.assertFalse(data['can_create'])                    # operario normal: solo aviso
        self.assertTrue(self._as(self.manager).scanner_catalog_search('AA120')['can_create'])

    def test_not_in_catalog(self):
        data = self._as(self.manager).scanner_catalog_search('NOEXISTE-999')
        self.assertEqual(data['articles'], [])
        with self.assertRaises(UserError) as error:
            self._as(self.manager).scanner_catalog_create(999999999)
        self.assertIn('No está en el catálogo de Sage', str(error.exception))
        self.assertFalse(self.Template.search([('default_code', '=ilike', 'NOEXISTE-999')]))

    def test_manager_creates_product(self):
        result = self._as(self.manager).scanner_catalog_create(self.article.id)
        self.assertEqual(result['status'], 'created')
        template = self.Template.search([('default_code', '=', 'AA120')])
        self.assertEqual(len(template), 1)
        self.assertEqual(template.name, 'AA120 AMPLIFICADOR MEZCLADOR 120W')
        self.assertTrue(template.is_storable)
        self.assertEqual(template.tracking, 'serial')
        self.assertFalse(template.company_id)
        self.assertFalse(template.categ_id.parent_id)           # categoría de marca de primer nivel
        self.assertEqual(template.categ_id.name, 'Cattest Atlas')
        self.assertEqual(self.env['rms.sage.article.map'].search([('article_code', '=', 'AAA120')]).product_tmpl_id,
                         template)
        # Queda elegido (leído/elegido) para volver a leer la etiqueta.
        self.assertEqual(self.operator.current_product_id, template.product_variant_id)
        self.assertTrue(self.operator.product_explicit)
        self.assertEqual(result['state']['product']['id'], template.product_variant_id.id)
        # Constancia: nota en el producto y lista para Administración.
        note = 'Creado desde el escáner del recuento %s por %s, artículo Sage A-AA120' % (
            self.session.name, self.manager.name)
        self.assertTrue(any(note in (message.body or '') for message in template.message_ids))
        log = self.env['rms.sage.scanner.product'].search([('product_tmpl_id', '=', template.id)])
        self.assertEqual((log.article_code, log.user_id, log.session_id, log.operator_name),
                         ('A-AA120', self.manager, self.session, 'Resp'))
        # Idempotente: pulsar otra vez (o desde la demo del mismo modelo) no crea otro.
        self.assertEqual(self._as(self.manager).scanner_catalog_create(self.article.id)['status'], 'exists')
        self.assertEqual(self._as(self.manager).scanner_catalog_create(self.demo.id)['status'], 'exists')
        self.assertEqual(len(self.Template.search([('default_code', '=ilike', 'AA120')])), 1)
        self.assertEqual(len(self.env['rms.sage.scanner.product'].search([])), 1)
        self.assertEqual(self._as(self.worker).scanner_catalog_search('AA120')['articles'][0]['status'], 'exists')
        # Releer: entra como alta de ese producto.
        scan = self.env['rms.stock.count.scan'].scanner_register(self.operator.id, 'SN-AA120-000111')
        self.assertEqual(scan['status'], 'ok')
        self.assertEqual(scan['scan']['product_name'], template.product_variant_id.display_name)
        self.assertTrue(scan['scan']['is_new_lot'])

    def test_worker_cannot_create(self):
        with self.assertRaises(UserError):
            self._as(self.worker).scanner_catalog_create(self.article.id)
        self.assertFalse(self.Template.search([('default_code', '=ilike', 'AA120')]))
        # Tampoco un usuario técnico con permisos, si está en la lista de excluidos.
        self.env['ir.config_parameter'].sudo().set_param(
            'rms_stock_count_session.no_scanner_create_logins', 'sage_sync, match_manager')
        with self.assertRaises(UserError):
            self._as(self.manager).scanner_catalog_create(self.article.id)
        with self.assertRaises(UserError):
            self._as(self.manager).sudo().scanner_catalog_create(self.article.id)   # sudo no se salta el grupo
        self.assertFalse(self.Template.search([('default_code', '=ilike', 'AA120')]))

    def test_never_duplicates_active_product(self):
        existing = self.env['product.template'].create({'name': 'Ya estaba', 'default_code': 'aa120'})
        self.assertEqual(self._as(self.worker).scanner_catalog_search('AA120')['articles'][0]['product_id'],
                         existing.product_variant_id.id)
        result = self._as(self.manager).scanner_catalog_create(self.article.id)
        self.assertEqual(result['status'], 'exists')
        self.assertEqual(result['product']['id'], existing.product_variant_id.id)
        self.assertEqual(self.Template.search([('default_code', '=ilike', 'AA120')]), existing)
        self.assertFalse(self.env['rms.sage.scanner.product'].search([]))

    def test_archived_product_is_reported_not_reactivated(self):
        archived = self.env['product.template'].create({'name': 'Archivado', 'default_code': 'AA120', 'active': False})
        self.assertEqual(self._as(self.worker).scanner_catalog_search('AA120')['articles'][0]['status'], 'archived')
        result = self._as(self.manager).scanner_catalog_create(self.article.id)
        self.assertEqual(result['status'], 'archived')
        self.assertIn('archivado', result['message'])
        self.assertFalse(archived.active)
        self.assertEqual(self.Template.search([('default_code', '=ilike', 'AA120')]), archived)
        self.assertFalse(self.operator.current_product_id)

    def test_respects_existing_alias(self):
        target = self.env['product.template'].create({'name': 'Producto con alias', 'default_code': 'OTRA-REF'})
        self.env['rms.sage.article.map'].create({'article_code': 'A-AA120', 'product_tmpl_id': target.id})
        result = self._as(self.manager).scanner_catalog_create(self.article.id)
        self.assertEqual(result['status'], 'exists')
        self.assertEqual(result['product']['id'], target.product_variant_id.id)
        self.assertFalse(self.Template.search([('default_code', '=ilike', 'AA120')]))

    def test_by_quantity(self):
        result = self._as(self.manager).scanner_catalog_create(self.cable.id, True)
        self.assertEqual(result['status'], 'created')
        template = self.Template.search([('default_code', '=', 'CBL77')])
        self.assertEqual(template.tracking, 'none')
        self.assertTrue(template.is_storable)
        self.assertTrue(self.env['rms.sage.scanner.product'].search([('product_tmpl_id', '=', template.id)]).by_quantity)
