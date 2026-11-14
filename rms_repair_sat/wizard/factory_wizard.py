# -*- coding: utf-8 -*-
from odoo import fields, models


class RmsRepairFactoryWizard(models.TransientModel):
    _name = 'rms.repair.factory.wizard'
    _description = 'Enviar equipo a fábrica (RA)'

    repair_id = fields.Many2one('repair.order', required=True)
    partner_id = fields.Many2one('res.partner', string='Fábrica / fabricante', required=True)
    rma_number = fields.Char(string='Nº RMA del fabricante')
    date = fields.Date(string='Fecha de envío', required=True, default=fields.Date.context_today)

    def action_confirm(self):
        self.ensure_one()
        self.repair_id._rms_send_to_factory(self.partner_id, self.rma_number, self.date)
        return {'type': 'ir.actions.act_window_close'}
