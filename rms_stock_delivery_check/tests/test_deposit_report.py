from odoo import Command
from odoo.tests import tagged

from .common import DeliveryCheckCommon

DELIVERY = 'rms_stock_delivery_check.report_deposit_delivery'
RETURN = 'rms_stock_delivery_check.report_deposit_return'


@tagged('post_install', '-at_install')
class TestDepositReport(DeliveryCheckCommon):

    def _html(self, report_ref, deposit, data=None):
        html, _fmt = self.env['ir.actions.report']._render_qweb_html(report_ref, deposit.ids, data=data)
        return html.decode()

    def _out_deposit(self):
        for name in ('RPT-A', 'RPT-B'):
            self._lot(self.galaxy, name)
        self._lot(self.console, 'RPT-C', 'demo')
        Cession = self.env['stock.cession'].with_user(self.operator)
        defaults = Cession.default_get(['location_src_id', 'location_dest_id', 'company_id'])
        deposit = Cession.create(dict(defaults, partner_id=self.partner.id, rms_line_ids=[
            Command.create({'product_id': self.galaxy.id, 'quantity': 2}),
            Command.create({'product_id': self.console.id, 'quantity': 1}),
            Command.create({'product_id': self.cover.id, 'quantity': 2}),
        ]))
        deposit.action_rms_prepare_out()
        out = deposit.picking_id
        for code in ('RPT-A', 'RPT-B', 'RPT-C'):
            self.assertEqual(self._scan(out, code).result, 'ok')
        out.with_user(self.operator).rms_check_set_qty(
            out.move_ids.filtered(lambda m: m.product_id == self.cover).id, 2)
        out.with_user(self.operator).rms_check_finish()
        out.with_user(self.operator).rms_check_validate()
        self.assertEqual(deposit.rms_deposit_state, 'out')
        return deposit

    def _return(self, deposit, serials):
        deposit.with_user(self.operator).action_rms_register_return()
        back = deposit.rms_picking_ids.filtered(
            lambda p: p.rms_deposit_role == 'return' and p.state != 'done')
        for code in serials:
            self.assertEqual(self._scan(back, code).result, 'ok')
        back.with_user(self.operator).rms_check_finish()
        back.with_user(self.operator).rms_check_validate()
        self.assertEqual(back.state, 'done')
        return back

    def test_delivery_report(self):
        deposit = self._out_deposit()
        html = self._html(DELIVERY, deposit)
        for text in ('Documento de entrega de material en depósito', deposit.name,
                     'RPT-A', 'RPT-B', 'RPT-C', 'Funda Galaxy',
                     'Entregado por RMS (nombre, fecha y firma)',
                     'Recibido por el cliente (nombre, DNI, fecha y firma)',
                     'propiedad de la empresa'):
            self.assertIn(text, html)
        # condiciones editables por parámetro de sistema
        self.env['ir.config_parameter'].sudo().set_param(
            'rms_stock_delivery_check.deposit_terms', 'Condiciones de prueba XYZ')
        html = self._html(DELIVERY, deposit)
        self.assertIn('Condiciones de prueba XYZ', html)
        self.assertNotIn('propiedad de la empresa', html)

    def test_return_report(self):
        deposit = self._out_deposit()
        self.assertFalse(deposit.rms_has_returns)
        back1 = self._return(deposit, ['RPT-A'])
        self.assertTrue(deposit.rms_has_returns)
        html = self._html(RETURN, deposit)
        for text in ('Documento de devolución de material en depósito', deposit.name, back1.name,
                     'Equipos devueltos', 'Sigue en depósito en el cliente',
                     'Devuelto por el cliente (nombre, DNI, fecha y firma)',
                     'Recibido en almacén por RMS (nombre, fecha y firma)'):
            self.assertIn(text, html)
        returned, _sep, still = html.partition('Sigue en depósito en el cliente')
        self.assertIn('RPT-A', returned)
        self.assertNotIn('RPT-B', returned)
        self.assertNotIn('RPT-C', returned)
        self.assertNotIn('RPT-A', still)
        self.assertIn('RPT-B', still)
        self.assertIn('RPT-C', still)
        self.assertIn('Funda Galaxy', still)  # lo que va por cantidad sigue fuera

        # segunda vuelta: el informe general trae una hoja por albarán,
        # y con data solo imprime la devolución concreta
        back2 = self._return(deposit, ['RPT-B'])
        html = self._html(RETURN, deposit)
        self.assertEqual(html.count('Documento de devolución de material en depósito'), 2)
        only2 = self._html(RETURN, deposit, data={'return_picking_id': back2.id})
        self.assertEqual(only2.count('Documento de devolución de material en depósito'), 1)
        returned, _sep, still = only2.partition('Sigue en depósito en el cliente')
        self.assertIn(back2.name, only2)
        self.assertNotIn(back1.name, only2)
        self.assertIn('RPT-B', returned)
        self.assertNotIn('RPT-A', only2)
        self.assertIn('RPT-C', still)

        # el botón del albarán pide solo su devolución
        action = back1.action_rms_print_deposit_return()
        self.assertEqual(action['data']['return_picking_id'], back1.id)
