from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class HrEmployeeCertification(models.Model):
    _name = 'hr.employee.certification'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Certificación de Empleado'
    _order = 'date_expiration, date_obtained desc'

    employee_id = fields.Many2one(
        'hr.employee', string='Empleado', required=True, ondelete='cascade',
        tracking=True, index=True)
    company_id = fields.Many2one(
        'res.company', related='employee_id.company_id', store=True, readonly=True)
    certification_type_id = fields.Many2one(
        'hr.certification.type', string='Certificación', required=True, tracking=True)
    category = fields.Selection(related='certification_type_id.category', store=True)
    is_recurring = fields.Boolean(
        related='certification_type_id.is_recurring', store=True, readonly=True)
    date_obtained = fields.Date(
        string='Fecha de Obtención', required=True,
        default=fields.Date.context_today, tracking=True)
    date_expiration = fields.Date(
        string='Fecha de Caducidad', compute='_compute_date_expiration',
        store=True, tracking=True)
    state = fields.Selection([
        ('valid', 'Vigente'),
        ('expiring', 'Próxima a Caducar'),
        ('expired', 'Caducada'),
        ('done', 'Registrada'),
    ], string='Estado', compute='_compute_state', store=True, tracking=True)
    document = fields.Binary(string='Documento', attachment=True)
    document_filename = fields.Char(string='Nombre del Documento')
    notes = fields.Text(string='Notas')
    active = fields.Boolean(default=True)

    @api.depends(
        'date_obtained',
        'certification_type_id.is_recurring',
        'certification_type_id.validity_months')
    def _compute_date_expiration(self):
        for cert in self:
            certification_type = cert.certification_type_id
            if certification_type.is_recurring and cert.date_obtained and certification_type.validity_months:
                cert.date_expiration = cert.date_obtained + relativedelta(
                    months=certification_type.validity_months)
            else:
                cert.date_expiration = False

    @api.depends(
        'date_expiration',
        'certification_type_id.is_recurring',
        'certification_type_id.reminder_days')
    def _compute_state(self):
        today = fields.Date.context_today(self)
        for cert in self:
            certification_type = cert.certification_type_id
            if not certification_type.is_recurring:
                cert.state = 'done'
            elif not cert.date_expiration:
                cert.state = 'valid'
            elif cert.date_expiration < today:
                cert.state = 'expired'
            elif cert.date_expiration <= today + relativedelta(
                    days=certification_type.reminder_days or 0):
                cert.state = 'expiring'
            else:
                cert.state = 'valid'

    @api.constrains('certification_type_id', 'document')
    def _check_required_document(self):
        for cert in self:
            if cert.certification_type_id.requires_document and not cert.document:
                raise ValidationError(
                    "El tipo de certificación '%s' requiere adjuntar un documento "
                    "justificativo." % cert.certification_type_id.name)

    def _get_reminder_responsible(self):
        self.ensure_one()
        return (
            self.certification_type_id.responsible_id
            or self.employee_id.parent_id.user_id
            or self.employee_id.user_id
        )

    @api.model
    def _cron_check_certification_renewals(self):
        recurring_certifications = self.search([('is_recurring', '=', True)])
        recurring_certifications._compute_state()

        activity_type = self.env.ref('mail.mail_activity_data_todo')
        to_notify = recurring_certifications.filtered(
            lambda cert: cert.state in ('expiring', 'expired'))
        for cert in to_notify:
            already_notified = cert.activity_ids.filtered(
                lambda activity: activity.activity_type_id == activity_type)
            if already_notified:
                continue
            responsible = cert._get_reminder_responsible()
            if not responsible:
                continue
            cert.activity_schedule(
                'mail.mail_activity_data_todo',
                date_deadline=cert.date_expiration,
                summary="Renovar certificación: %s" % cert.certification_type_id.name,
                note=(
                    "La certificación <b>%s</b> de <b>%s</b> %s (%s). "
                    "Por favor, gestiona su renovación." % (
                        cert.certification_type_id.name,
                        cert.employee_id.name,
                        "ha caducado" if cert.state == 'expired' else "está próxima a caducar",
                        cert.date_expiration,
                    )
                ),
                user_id=responsible.id,
            )
