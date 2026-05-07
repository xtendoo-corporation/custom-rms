from odoo import models

class Import(models.TransientModel):
    _inherit = 'base_import.import'

    def do(self, fields, columns, options, dryrun=False):
        # Si el modelo que estamos importando es res.partner, 
        # inyectamos la bandera nativa de odoo para saltarnos la validación del NIF
        if self.res_model == 'res.partner':
            self = self.with_context(no_vat_validation=True)
        return super(Import, self).do(fields, columns, options, dryrun=dryrun)
