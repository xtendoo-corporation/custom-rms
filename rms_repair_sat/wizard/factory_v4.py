from odoo import fields, models
from odoo.exceptions import UserError


class RepairWarrantyRejectWizard(models.TransientModel):
    _name = 'rms.repair.warranty.reject.wizard'
    _description = 'Rechazo de garantía de fábrica'

    repair_id = fields.Many2one('repair.order', required=True)
    reason = fields.Text(string='Motivo', required=True)

    def action_confirm(self):
        self.ensure_one()
        self.repair_id._rms_check_sat_access('technician')
        if not self.repair_id.under_warranty:
            raise UserError('El equipo no está marcado en garantía.')
        self.repair_id._rms_reject_warranty(self.reason)
        return {'type': 'ir.actions.act_window_close'}


class RepairDestroyWizard(models.TransientModel):
    _name = 'rms.repair.destroy.wizard'
    _description = 'Destrucción por indicación de fábrica'

    repair_id = fields.Many2one('repair.order', required=True)
    authorization_ref = fields.Char(string='Autorización', required=True)
    note = fields.Text(string='Nota')

    def action_confirm(self):
        self.ensure_one()
        self.repair_id._rms_destroy_factory(self.authorization_ref, self.note)
        return {'type': 'ir.actions.act_window_close'}


class RepairFactoryReturnV4(models.TransientModel):
    _inherit = 'rms.repair.factory.return.wizard'

    result = fields.Selection(selection_add=[
        ('warranty_rejected', 'Garantía rechazada por la fábrica'),
        ('destroyed', 'Destruido por indicación de fábrica'),
    ], ondelete={'warranty_rejected': 'set default', 'destroyed': 'set default'})
    warranty_rejected_reason = fields.Text(string='Motivo del rechazo')
    authorization_ref = fields.Char(string='Autorización de destrucción')
    destruction_note = fields.Text(string='Nota de destrucción')

    def action_confirm(self):
        self.ensure_one()
        if self.result not in ('warranty_rejected', 'destroyed'):
            repair = self.repair_id
            # El rechazo sin retorno ya dejó la fase en diagnóstico. La vuelta
            # física posterior no debe adelantarla a reparación.
            keep_diagnosis = (self.result == 'repaired' and repair.rms_warranty_rejected
                              and repair.rms_stage == 'diagnosis' and repair.rms_physically_at_factory)
            result = super().action_confirm()
            if keep_diagnosis:
                repair.rms_stage = 'diagnosis'
            return result
        repair = self.repair_id
        repair._rms_check_sat_access('technician')
        if repair.rms_stage != 'factory' and not repair.rms_physically_at_factory:
            raise UserError('El equipo no está en fábrica.')
        warehouse = repair._rms_sat_locations()
        if self.result == 'warranty_rejected':
            if not (self.warranty_rejected_reason or '').strip():
                raise UserError('Indica el motivo del rechazo de garantía.')
            repair._rms_customer_move(warehouse.rms_sat_factory_location_id, warehouse.rms_sat_location_id,
                                      'Vuelta de fábrica')
            repair.write({'rms_factory_result': 'warranty_rejected',
                          'rms_factory_back_date': fields.Date.context_today(repair),
                          'product_location_src_id': warehouse.rms_sat_location_id.id,
                          'product_location_dest_id': warehouse.rms_sat_location_id.id})
            repair._rms_reject_warranty(self.warranty_rejected_reason)
        else:
            repair._rms_destroy_factory(self.authorization_ref, self.destruction_note,
                                        location=warehouse.rms_sat_factory_location_id)
        return {'type': 'ir.actions.act_window_close'}
