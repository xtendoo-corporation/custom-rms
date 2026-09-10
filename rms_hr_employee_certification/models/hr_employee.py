from odoo import api, fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    certification_ids = fields.One2many(
        'hr.employee.certification', 'employee_id', string='Certificaciones')
    certification_count = fields.Integer(
        string='Nº Certificaciones', compute='_compute_certification_count')
    certification_alert_count = fields.Integer(
        string='Certificaciones a Renovar', compute='_compute_certification_count')

    @api.depends('certification_ids.state')
    def _compute_certification_count(self):
        for employee in self:
            employee.certification_count = len(employee.certification_ids)
            employee.certification_alert_count = len(employee.certification_ids.filtered(
                lambda cert: cert.state in ('expiring', 'expired')))
