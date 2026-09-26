# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

# default_code de las categorías de gasto existentes (product.product,
# can_be_expensed=True). Heurística de palabras clave en español para
# rellenar la categoría cuando xtendoo_hr_expense_ai no la haya asignado ya
# (su wizard sólo documenta fecha/descripción/importe/proveedor).
EXPENSE_CATEGORY_KEYWORDS = {
    'FOOD': [
        'restaurante', 'bar ', 'cafeteria', 'cafetería', 'menu', 'menú',
        'comida', 'almuerzo', 'cena', 'desayuno',
    ],
    'TRANS & ACC': [
        'taxi', 'uber', 'cabify', 'renfe', 'avion', 'avión', 'vuelo',
        'hotel', 'parking', 'aparcamiento', 'peaje', 'gasolina',
        'gasolinera', 'combustible', 'autopista', 'tren', 'billete',
    ],
    'COMM': [
        'telefono', 'teléfono', 'movil', 'móvil', 'internet', 'vodafone',
        'movistar', 'orange', 'telefonica', 'telefónica',
    ],
    'GIFT': ['regalo', 'flores', 'obsequio'],
    'MIL': ['kilometraje', 'km recorridos', 'dietas'],
}
EXPENSE_CATEGORY_FALLBACK = 'EXP_GEN'


class HrExpense(models.Model):
    _inherit = 'hr.expense'

    created_from_email_alias = fields.Boolean(
        string="Creado por email (alias de Gastos)", default=False, copy=False)
    ai_attachments_split = fields.Boolean(
        string="Adjuntos del email ya repartidos", default=False, copy=False)
    ai_import_attempts = fields.Integer(
        string="Intentos de importación con IA", default=0, copy=False)
    ai_source_attachment_id = fields.Many2one(
        'ir.attachment', string="Adjunto asignado para la IA", copy=False)

    @api.model
    def message_new(self, msg_dict, custom_values=None):
        expense = super().message_new(msg_dict, custom_values=custom_values)
        expense.created_from_email_alias = True
        # El parseo del asunto (ajeno a este módulo) a veces coge un número
        # suelto de la propia fecha del asunto y lo dejaba como importe
        # (p. ej. "15" de "15 sept 2026"). Se deja en 0 hasta que la IA
        # rellene el importe real, en vez de mostrar esa cifra falsa.
        expense.write({
            'total_amount': 0.0,
            'total_amount_currency': 0.0,
        })
        # Ese mismo parseo del asunto manda un aviso de confirmación con un
        # importe/categoría provisionales (a veces inventados, como el caso
        # anterior) antes de que la IA corrija nada. Se retira del chatter
        # porque queda desactualizado y confunde; la nota de la IA (más
        # abajo, en _rms_finalize_ai_import) ya deja los datos buenos.
        stale_notice = expense.message_ids.filtered(
            lambda m: m.body and "ha sido registrado con éxito" in m.body
        )
        if stale_notice:
            stale_notice.sudo().unlink()
        return expense

    def _rms_get_candidate_attachments(self, min_bytes=0):
        self.ensure_one()
        attachments = self.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'hr.expense'),
            ('res_id', '=', self.id),
        ], order='id')
        return attachments.filtered(
            lambda a: (
                (a.mimetype or '').startswith('image/') or a.mimetype == 'application/pdf'
            ) and a.file_size >= min_bytes
        )

    def _rms_split_email_attachments(self):
        self.ensure_one()
        self.ai_attachments_split = True

        min_bytes = int(self.env['ir.config_parameter'].sudo().get_param(
            'rms_hr_expense_ai_email.min_attachment_bytes', 15000))
        tickets = self._rms_get_candidate_attachments(min_bytes=min_bytes)
        if not tickets:
            return self.browse()

        # El primer ticket se queda en este mismo gasto (sus adjuntos no se
        # tocan: su historial ya muestra el correo original completo, con
        # todas las fotos).
        self.ai_source_attachment_id = tickets[0].id
        if len(tickets) <= 1:
            return self.browse()

        total = len(tickets)
        new_expenses = self.browse()
        for index, own_ticket in enumerate(tickets[1:], start=2):
            new_expense = self.copy({
                'created_from_email_alias': True,
                'ai_attachments_split': True,
                'ai_processed': False,
                'ai_has_corrections': False,
                'ai_import_attempts': 0,
                'ai_source_attachment_id': False,
                'attachment_ids': [(5, 0, 0)],
            })
            # Se copian TODOS los tickets del correo (no solo el suyo) en
            # cada gasto repartido, para que su historial muestre también
            # el correo completo con las fotos de todos los tickets, igual
            # que puede verse en el gasto original. Sólo se usa "own_copy"
            # (la copia de su propio ticket) para la extracción con IA.
            copies = self.env['ir.attachment']
            own_copy = self.env['ir.attachment']
            for ticket in tickets:
                ticket_copy = ticket.sudo().copy({'res_id': new_expense.id})
                copies |= ticket_copy
                if ticket.id == own_ticket.id:
                    own_copy = ticket_copy
            new_expense.ai_source_attachment_id = own_copy.id
            new_expense.message_post(
                body=_(
                    "Ticket %(index)s de %(total)s detectado en el correo "
                    "original (repartido desde el gasto #%(source)s). Se "
                    "adjuntan también los demás tickets del mismo correo "
                    "como referencia; este gasto se analiza con el ticket "
                    "%(index)s.",
                    index=index, total=total, source=self.id,
                ),
                attachment_ids=copies.ids,
            )
            new_expenses |= new_expense

        self.message_post(body=_(
            "Se han detectado %(total)s tickets en este correo: se han creado "
            "%(extra)s gastos adicionales en borrador, uno por cada ticket.",
            total=total, extra=total - 1,
        ))
        return new_expenses

    @api.model
    def _cron_process_pending_ai_email_expenses(self):
        max_attempts = int(self.env['ir.config_parameter'].sudo().get_param(
            'rms_hr_expense_ai_email.max_attempts', 3))
        batch_limit = int(self.env['ir.config_parameter'].sudo().get_param(
            'rms_hr_expense_ai_email.batch_limit', 20))
        # created_from_email_alias cubre los que llegan por correo (algunos
        # todavía sin repartir/analizar); ai_source_attachment_id cubre los
        # de otros orígenes (p. ej. rms_hr_expense_quick_capture) cuyo
        # primer intento, síncrono, haya fallado y necesite reintentarse.
        expenses = self.sudo().search([
            ('state', '=', 'draft'),
            ('ai_processed', '=', False),
            ('ai_import_attempts', '<', max_attempts),
            '|',
                ('created_from_email_alias', '=', True),
                ('ai_source_attachment_id', '!=', False),
        ], limit=batch_limit)
        for expense in expenses:
            # El reparto se hace aquí, en el cron, y no al recibir el correo:
            # depender del orden exacto de los mensajes creados en el hilo
            # (correo entrante, avisos de otros módulos, etc.) no es fiable.
            # Aquí solo miramos el estado ya persistido de los adjuntos.
            new_expenses = self.browse()
            if not expense.ai_attachments_split:
                new_expenses = expense._rms_split_email_attachments()
                # Un correo puede traer muchos tickets (un comercial que
                # manda 30 fotos de golpe en vez de 30 correos): se guarda
                # el reparto ya mismo para no perderlo si el proceso se
                # interrumpe a mitad de las llamadas a la IA que vienen
                # a continuación, una por cada ticket.
                self.env.cr.commit()
            for to_process in expense + new_expenses:
                to_process._rms_run_ai_import(max_attempts)
                # Cada ticket se procesa con una llamada a la IA por
                # separado (pueden ser bastantes en un correo con muchos
                # adjuntos): se confirma cada uno según se completa, para
                # no perder los ya hechos si algo corta la pasada a mitad.
                self.env.cr.commit()

    def _rms_run_ai_import(self, max_attempts):
        self.ensure_one()
        attachment = self.ai_source_attachment_id
        if not attachment:
            attachment = self._rms_get_candidate_attachments()[:1]
        if not attachment:
            return

        self.ai_import_attempts += 1
        try:
            with self.env.cr.savepoint():
                wizard = self.env['hr.expense.ai.wizard'].sudo().create({
                    'expense_id': self.id,
                    'attachment_file': attachment.datas,
                    'attachment_name': attachment.name,
                })
                wizard.action_analyze()
                wizard.action_apply()
        except Exception as exc:  # noqa: BLE001 - errores externos (Gemini, red, JSON...)
            _logger.warning(
                "Fallo al procesar el gasto #%s con IA (intento %s/%s): %s",
                self.id, self.ai_import_attempts, max_attempts, exc,
            )
            # Aviso inmediato en cada intento fallido, no solo al agotar los
            # 3: si la foto en sí no se puede leer (mala calidad, borrosa),
            # reintentar la misma imagen no lo va a arreglar, así que no
            # tiene sentido dejar al usuario sin ninguna noticia hasta que
            # se agoten los reintentos.
            self.ai_has_corrections = True
            if self.ai_import_attempts >= max_attempts:
                self.message_post(body=_(
                    "NO ES POSIBLE ESCANEARLO: la IA no ha podido procesar este "
                    "ticket tras %(attempts)s intentos. Revísalo manualmente "
                    "(importe, proveedor y categoría) antes de aprobarlo."
                    "\nError: %(error)s",
                    attempts=self.ai_import_attempts, error=str(exc)[:500],
                ))
            else:
                self.message_post(body=_(
                    "NO ES POSIBLE ESCANEARLO (intento %(attempts)s de "
                    "%(max)s). Se reintentará automáticamente; si vuelve a "
                    "fallar tras el último intento, revísalo manualmente.",
                    attempts=self.ai_import_attempts, max=max_attempts,
                ))
            return

        self._rms_finalize_ai_import()

    def _rms_finalize_ai_import(self):
        self.ensure_one()
        self.ai_has_corrections = False
        if not self.ai_processed:
            self.ai_processed = True
        if not self.product_id:
            category = self._rms_guess_expense_category()
            if category:
                self.product_id = category

        # El aviso automático que se envía al crear el gasto (parseo del
        # asunto) queda desactualizado en cuanto la IA corrige los datos:
        # se deja esta nota de seguimiento con los valores ya corregidos
        # para que quede claro cuál es el dato bueno.
        self.message_post(body=_(
            "IA: datos corregidos automáticamente.\n"
            "Proveedor: %(vendor)s\n"
            "Importe: %(amount).2f %(currency)s\n"
            "Fecha: %(date)s\n"
            "Categoría: %(category)s",
            vendor=self.vendor_id.name or "(no detectado)",
            amount=self.total_amount,
            currency=self.currency_id.name or "",
            date=self.date or "",
            category=self.product_id.name or "(sin asignar)",
        ))

    def _rms_guess_expense_category(self):
        self.ensure_one()
        text = ' '.join(filter(None, [
            self.vendor_id.name, self.name, self.description,
        ])).lower()

        Product = self.env['product.product'].sudo()
        for default_code, keywords in EXPENSE_CATEGORY_KEYWORDS.items():
            if any(keyword in text for keyword in keywords):
                product = Product.search([
                    ('default_code', '=', default_code),
                    ('can_be_expensed', '=', True),
                ], limit=1)
                if product:
                    return product

        return Product.search([
            ('default_code', '=', EXPENSE_CATEGORY_FALLBACK),
            ('can_be_expensed', '=', True),
        ], limit=1)
