from odoo import api, fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    rms_certification_ids = fields.One2many(
        'rms.hr.employee.certification', 'employee_id', string='Certificaciones')
    rms_certification_count = fields.Integer(
        string='Nº Certificaciones', compute='_compute_rms_certification_count')
    rms_certification_alert_count = fields.Integer(
        string='Certificaciones a Renovar', compute='_compute_rms_certification_count')

    @api.depends('rms_certification_ids.state')
    def _compute_rms_certification_count(self):
        for employee in self:
            employee.rms_certification_count = len(employee.rms_certification_ids)
            employee.rms_certification_alert_count = len(employee.rms_certification_ids.filtered(
                lambda cert: cert.state in ('expiring', 'expired')))
