from odoo import models


class RepairReceiptAcknowledgement(models.Model):
    _inherit = 'repair.order'

    def action_rms_register_entry(self):
        # El botón ya ignora equipos registrados: no enviar de nuevo al repetirlo.
        pending = self.filtered(lambda repair: not repair.rms_in_sat)
        result = super().action_rms_register_entry()
        template = self.env.ref('rms_repair_sat.mail_template_sat_receipt')
        for repair in pending.filtered(lambda r: r.rms_in_sat and r.rms_owner_type == 'customer'
                                                  and r.rms_entry_way in ('courier', 'pickup')):
            email = repair.rms_contact_id.email or repair.partner_id.email
            if email:
                template.send_mail(repair.id, force_send=False, email_values={'email_to': email})
            else:
                repair.message_post(body='No se ha enviado el acuse de recibo: falta el correo del contacto y del cliente.')
        return result
