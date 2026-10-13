from odoo import models


class Import(models.TransientModel):
    _inherit = 'base_import.import'

    def execute_import(self, fields, columns, options, dryrun=False):
        # Al importar contactos con el importador nativo de Odoo
        # (Favoritos > Importar registros), activamos la bandera estándar
        # de base_vat para no validar el NIF. El alta manual desde el
        # formulario sigue validándolo con normalidad.
        if self.res_model == 'res.partner':
            self = self.with_context(no_vat_validation=True)
        return super().execute_import(fields, columns, options, dryrun=dryrun)
