# -*- coding: utf-8 -*-

from odoo import models
from odoo.exceptions import AccessError

from .restrictions import is_comercial


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    def unlink(self):
        # Los comerciales pueden borrar sus oportunidades, pero no las de otros.
        if not self.env.su and is_comercial(self.env) and any(
            lead.user_id != self.env.user for lead in self
        ):
            raise AccessError('Solo puedes eliminar tus propias oportunidades.')
        return super().unlink()
