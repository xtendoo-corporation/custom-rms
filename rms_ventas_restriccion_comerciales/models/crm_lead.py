# -*- coding: utf-8 -*-

from odoo import models
from odoo.exceptions import AccessError

from .restrictions import is_comercial, readable_suggested_recipients


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    def unlink(self):
        # Los comerciales pueden borrar sus oportunidades, pero no las de otros.
        if not self.env.su and is_comercial(self.env) and any(
            lead.user_id != self.env.user for lead in self
        ):
            raise AccessError('Solo puedes eliminar tus propias oportunidades.')
        return super().unlink()

    def _message_get_suggested_recipients_batch(self, *args, **kwargs):
        # El cálculo lee el email de los seguidores y de los autores y
        # destinatarios del último mensaje, que pueden ser contactos que el
        # comercial no puede leer: sin sudo, el chatter falla con AccessError al
        # abrir el documento (INC-00007). Se calcula con sudo y se quitan de la
        # sugerencia los contactos que no puede leer.
        if self.env.su or not is_comercial(self.env):
            return super()._message_get_suggested_recipients_batch(*args, **kwargs)
        # sudo: res.partner - seguidores y autores que el comercial no puede leer
        suggested = super(CrmLead, self.sudo())._message_get_suggested_recipients_batch(*args, **kwargs)
        return readable_suggested_recipients(self.env, suggested)
