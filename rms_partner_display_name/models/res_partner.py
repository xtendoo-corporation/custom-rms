# -*- coding: utf-8 -*-
from odoo import models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def _get_complete_name(self):
        """Para contactos individuales, muestra "Nombre, Empresa" en vez de
        "Empresa, Nombre" (orden por defecto de Odoo), que dificultaba
        localizar al contacto en listados largos.
        """
        self.ensure_one()
        if not self.is_company:
            name = self.name or ''
            company_name = self.commercial_company_name or (self.parent_id.name if self.parent_id else False)
            if company_name and company_name != name:
                return "%s, %s" % (name, company_name)
            return name
        return super()._get_complete_name()
