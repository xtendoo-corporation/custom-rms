# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HrExpenseQuickCapture(models.TransientModel):
    _name = 'hr.expense.quick.capture'
    _description = "Captura rápida de ticket de gasto (foto con el móvil)"

    @api.model
    def create_from_photo(self, image, filename):
        """Crea un hr.expense a partir de una foto y lo procesa con IA al
        momento. Se llama por RPC desde la pantalla ligera de captura
        rápida (rms_hr_expense_quick_capture.capture, sin formulario
        clásico de Odoo por medio)."""
        if not image:
            raise UserError(_("Falta la foto del ticket."))

        employee = self.env.user.employee_id
        if not employee:
            raise UserError(_(
                "Tu usuario no tiene un empleado asociado: no se puede "
                "crear el gasto a tu nombre."
            ))

        expense = self.env['hr.expense'].create({
            'name': _("Ticket %s") % fields.Datetime.context_timestamp(
                self, fields.Datetime.now()
            ).strftime('%d/%m/%Y %H:%M'),
            'employee_id': employee.id,
            'date': fields.Date.context_today(self),
            'total_amount': 0.0,
        })
        attachment = self.env['ir.attachment'].create({
            'name': filename or 'ticket.jpg',
            'datas': image,
            'res_model': 'hr.expense',
            'res_id': expense.id,
        })
        expense.ai_source_attachment_id = attachment.id

        # Se procesa al momento (no se espera al cron): es una sola foto
        # recién hecha, tiene sentido dar feedback inmediato en vez de
        # esperar al siguiente ciclo. Reutiliza el mismo motor de IA que
        # ya usa el correo de gastos (rms_hr_expense_ai_email), incluido
        # su manejo de reintentos/errores y el aviso "NO ES POSIBLE
        # ESCANEARLO" si falla (el cron generalizado de ese módulo
        # reintentará automáticamente si este primer intento falla).
        max_attempts = int(self.env['ir.config_parameter'].sudo().get_param(
            'rms_hr_expense_ai_email.max_attempts', 3))
        expense._rms_run_ai_import(max_attempts)

        return {
            'expense_id': expense.id,
            'ai_processed': expense.ai_processed,
            'has_corrections': expense.ai_has_corrections,
            'vendor': expense.vendor_id.name or '',
            'amount': expense.total_amount,
            'currency': expense.currency_id.name or '',
            'category': expense.product_id.name or '',
        }
