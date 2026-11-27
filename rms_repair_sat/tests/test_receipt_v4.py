import base64
from unittest.mock import patch

from odoo import Command
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSatReceiptV4(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env['stock.warehouse'].search([('company_id', '=', cls.env.company.id)], limit=1)
        cls.warehouse.code = 'RMS1'
        cls.env['stock.warehouse']._rms_setup_sat()
        cls.customer = cls.env['res.partner'].create({'name': 'Cliente acuse', 'email': 'cliente@example.test'})
        cls.contact = cls.env['res.partner'].create({'name': 'Contacto acuse', 'parent_id': cls.customer.id,
                                                     'email': 'contacto@example.test'})
        cls.product = cls.env['product.product'].create({'name': 'Equipo acuse', 'is_storable': True,
                                                         'tracking': 'serial'})
        cls.accessory = cls.env.ref('rms_repair_sat.accessory_none')

    def _repair(self, way, serial, owner='customer'):
        repair = self.env['repair.order'].create({'partner_id': self.customer.id, 'rms_contact_id': self.contact.id,
            'product_id': self.product.id, 'rms_site': 'madrid', 'rms_serial_in': serial,
            'rms_owner_type': owner, 'rms_entry_way': way, 'rms_tracking_ref': 'ENV-1', 'rms_fault': 'No enciende',
            'rms_accessory_ids': [Command.set(self.accessory.ids)]})
        self.env['ir.attachment'].create({'name': 'foto.png', 'res_model': 'repair.order', 'res_id': repair.id,
            'mimetype': 'image/png', 'datas': base64.b64encode(b'foto')})
        return repair

    def _mail(self, repair):
        return self.env['mail.mail'].sudo().search([('model', '=', 'repair.order'), ('res_id', '=', repair.id),
                                                    ('subject', 'like', 'SAT: acuse de recibo')])

    def test_courier_creates_mail_message_and_pdf_once(self):
        repair = self._repair('courier', 'ACUSE-1')
        template = self.env.ref('rms_repair_sat.mail_template_sat_receipt')
        self.assertIn(self.env.ref('rms_repair_sat.action_report_receipt'), template.report_template_ids)
        # Odoo test mode no genera PDF real: se verifica que la plantilla pide
        # el informe y que el mensaje guarda su contenido como adjunto PDF.
        with patch.object(type(self.env['ir.actions.report']), '_render_qweb_pdf', autospec=True,
                          return_value=(b'%PDF-1.4 test', 'pdf')) as render:
            repair.action_rms_register_entry()
            repair.action_rms_register_entry()
        mail = self._mail(repair)
        self.assertEqual(len(mail), 1)
        self.assertEqual(mail.email_to, self.contact.email)
        self.assertEqual(len(mail.attachment_ids), 1)
        self.assertTrue(mail.attachment_ids.name.endswith('.pdf'))
        self.assertEqual(base64.b64decode(mail.attachment_ids.datas), b'%PDF-1.4 test')
        self.assertEqual(mail.mail_message_id.model, 'repair.order')
        self.assertEqual(mail.mail_message_id.res_id, repair.id)
        self.assertEqual(render.call_count, 1)

    def test_hand_and_company_do_not_send(self):
        for way, owner, serial in [('hand', 'customer', 'ACUSE-2'), ('pickup', 'company', 'ACUSE-3')]:
            repair = self._repair(way, serial, owner)
            repair.action_rms_register_entry()
            self.assertFalse(self._mail(repair))

    def test_receipt_text_depends_on_entry_way(self):
        report = self.env.ref('rms_repair_sat.action_report_receipt')
        for way in ('hand', 'courier', 'pickup'):
            repair = self._repair(way, 'HTML-' + way)
            html, _format = self.env['ir.actions.report']._render_qweb_html(report, [repair.id])
            html = html.decode() if isinstance(html, bytes) else html
            self.assertEqual('Firma del cliente:' in html, way == 'hand')
            self.assertEqual('Equipo recibido por transporte el' in html, way != 'hand')
