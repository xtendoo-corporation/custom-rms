from odoo import models

class ResPartner(models.Model):
    _inherit = 'res.partner'

    def _check_vat(self, validation="error"):
        # Desactivamos COMPLETA e INCONDICIONALMENTE la validación
        # mientras este módulo esté instalado.
        return
