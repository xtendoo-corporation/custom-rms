# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


class HrExpenseQuickCapture(models.TransientModel):
    _name = 'hr.expense.quick.capture'
    _description = "Captura rápida de ticket de gasto (foto con el móvil)"

    image = fields.Binary(string="Foto del ticket", required=True)
    image_filename = fields.Char(string="Nombre del archivo", default="ticket.jpg")
    state = fields.Selection([
        ('draft', "Borrador"),
        ('done', "Hecho"),
    ], default='draft')
    expense_id = fields.Many2one('hr.expense', string="Gasto creado", readonly=True)

    def action_capture(self):
        self.ensure_one()
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
            'name': self.image_filename or 'ticket.jpg',
            'datas': self.image,
            'res_model': 'hr.expense',
            'res_id': expense.id,
        })
        expense.ai_source_attachment_id = attachment.id

        # Se procesa al momento (no se espera al cron): es una sola foto
        # recién hecha, tiene sentido dar feedback inmediato en vez de
        # esperar al siguiente ciclo. Reutiliza el mismo motor de IA que
        # ya usa el correo de gastos (rms_hr_expense_ai_email), incluido
        # su manejo de reintentos/errores y el aviso "NO ES POSIBLE
        # ESCANEARLO" si falla.
        max_attempts = int(self.env['ir.config_parameter'].sudo().get_param(
            'rms_hr_expense_ai_email.max_attempts', 3))
        expense._rms_run_ai_import(max_attempts)

        self.write({'expense_id': expense.id, 'state': 'done'})
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hr.expense',
            'res_id': expense.id,
            'view_mode': 'form',
            'target': 'current',
        }
