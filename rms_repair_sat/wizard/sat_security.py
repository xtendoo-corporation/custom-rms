from odoo import models

from ..models.sat_security import _require


class FactoryWizardSecurity(models.TransientModel):
    _inherit = 'rms.repair.factory.wizard'

    def action_confirm(self):
        _require(self.env, 'technician')
        return super().action_confirm()


class FactoryReturnWizardSecurity(models.TransientModel):
    _inherit = 'rms.repair.factory.return.wizard'

    def action_confirm(self):
        _require(self.env, 'technician')
        return super().action_confirm()


class SwapWizardSecurity(models.TransientModel):
    _inherit = 'rms.repair.swap.wizard'

    def action_confirm(self):
        _require(self.env, 'technician')
        return super().action_confirm()

