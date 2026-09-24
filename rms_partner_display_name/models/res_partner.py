# -*- coding: utf-8 -*-
from odoo import models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def _get_complete_name(self):
        """No antepone el nombre de la empresa para contactos individuales.

        Por defecto Odoo muestra "Empresa, Nombre" para los contactos hijos
        de una empresa, lo que dificulta la lectura en listados largos.
        """
        self.ensure_one()
        if not self.is_company:
            return self.name or ''
        return super()._get_complete_name()
