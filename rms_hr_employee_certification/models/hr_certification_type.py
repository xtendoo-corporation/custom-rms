from odoo import api, fields, models


class HrCertificationType(models.Model):
    _name = 'hr.certification.type'
    _description = 'Tipo de Certificación de Empleado'
    _order = 'name'

    name = fields.Char(string='Nombre', required=True, translate=True)
    code = fields.Char(string='Código Interno')
    category = fields.Selection([
        ('training', 'Formación'),
        ('consent', 'Consentimiento / Firma'),
        ('medical', 'Reconocimiento Médico'),
        ('other', 'Otro'),
    ], string='Categoría', default='training', required=True)
    is_recurring = fields.Boolean(
        string='Requiere Renovación Periódica', default=True,
        help="Marcar si esta certificación caduca y debe renovarse periódicamente "
             "(p.ej. formación anual de PRL). Desmarcar si es un reconocimiento único "
             "que no caduca (p.ej. firma de un consentimiento).")
    validity_months = fields.Integer(
        string='Validez (meses)', default=12,
        help="Meses de validez desde la fecha de obtención. Solo aplica si la "
             "certificación requiere renovación periódica.")
    reminder_days = fields.Integer(
        string='Aviso de Renovación (días antes)', default=30,
        help="Días de antelación con los que se debe avisar antes de la caducidad.")
    requires_document = fields.Boolean(
        string='Requiere Documento Adjunto',
        help="Si está marcado, no se podrá registrar esta certificación sin adjuntar "
             "el documento justificativo (diploma, certificado, consentimiento firmado, etc.).")
    responsible_id = fields.Many2one(
        'res.users', string='Responsable de Seguimiento',
        help="Usuario al que se le asignará la actividad de aviso cuando una certificación "
             "de este tipo esté próxima a caducar o haya caducado. Si se deja vacío, se "
             "asignará al responsable del empleado.")
    active = fields.Boolean(default=True)
    description = fields.Text(string='Descripción')

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'Ya existe un tipo de certificación con este código.'),
    ]

    @api.onchange('is_recurring')
    def _onchange_is_recurring(self):
        if not self.is_recurring:
            self.validity_months = 0
