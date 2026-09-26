# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HrExpenseQuickCapture(models.TransientModel):
    _name = 'hr.expense.quick.capture'
    _description = "Captura rápida de ticket de gasto (foto con el móvil)"

    @api.model
    def create_from_photo(self, image, filename):
        """Crea un hr.expense a partir de una foto y deja marcado el
        adjunto para que el cron de rms_hr_expense_ai_email lo procese
        con IA en segundo plano. Se llama por RPC desde la pantalla
        ligera de captura rápida (rms_hr_expense_quick_capture.capture,
        sin formulario clásico de Odoo por medio).

        No se llama a la IA aquí, en la misma petición: una foto real
        desde el móvil (4G) más el tiempo de Gemini puede tardar más de
        lo que aguanta la conexión/el proxy antes de cortarse, y esa
        petición fallando no debe impedir que el gasto quede guardado.
        Subir la foto es rápido y fiable; el análisis con IA es lo que
        puede tardar, así que se deja para el cron.
        """
        if not image:
            raise UserError(_("Falta la foto del ticket."))

        # self.env.user.employee_id solo mira la compañía activa en este
        # momento; si no coincide exactamente con la del registro de
        # empleado (habitual con varias compañías), sale vacío aunque el
        # usuario sí tenga un empleado vinculado. employee_ids no tiene
        # esa restricción.
        employee = self.env.user.employee_id or self.env.user.employee_ids[:1]
        if not employee:
            raise UserError(_(
                "Tu usuario no tiene ningún empleado vinculado (revisa el "
                "campo \"Usuario\" en tu ficha de Empleado): no se puede "
                "crear el gasto a tu nombre."
            ))

        # El gasto tiene que crearse en la misma compañía que el empleado
        # (Odoo no permite mezclar compañías entre hr.expense y su
        # employee_id): no se puede dejar que use la compañía activa de
        # la sesión sin más, con varias compañías puede no coincidir.
        expense = self.env['hr.expense'].with_company(employee.company_id).create({
            'name': _("Ticket %s") % fields.Datetime.context_timestamp(
                self, fields.Datetime.now()
            ).strftime('%d/%m/%Y %H:%M'),
            'employee_id': employee.id,
            'company_id': employee.company_id.id,
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

        return {'expense_id': expense.id}
