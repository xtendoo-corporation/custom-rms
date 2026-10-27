from datetime import timedelta

from odoo import api, fields, models


class PortalAccessLog(models.Model):
    _name = 'rms.portal.access.log'
    _description = 'Acceso al Portal de Clientes'
    _order = 'login_date desc'
    _rec_name = 'login'

    partner_id = fields.Many2one('res.partner', string='Contacto', index=True, readonly=True)
    user_id = fields.Many2one('res.users', string='Usuario', index=True, readonly=True)
    login = fields.Char(string='Login', readonly=True)
    login_date = fields.Datetime(string='Fecha de acceso', required=True, index=True, readonly=True)
    ip_address = fields.Char(string='Dirección IP', readonly=True)
    portal_profile = fields.Selection(
        [
            ('customer', 'Cliente'),
            ('marketing', 'Colaborador de Marketing'),
            ('projects', 'Proyectos'),
        ],
        string='Perfil de portal', readonly=True,
    )
    activity_ids = fields.One2many('rms.portal.activity', 'access_log_id', string='Actividad', readonly=True)
    activity_count = fields.Integer(string='Acciones', compute='_compute_activity_count')

    def _compute_activity_count(self):
        counts = dict(self.env['rms.portal.activity']._read_group(
            [('access_log_id', 'in', self.ids)], ['access_log_id'], ['__count'],
        ))
        for log in self:
            log.activity_count = counts.get(log, 0)

    @api.model
    def _cron_purge_old_logs(self):
        """Borra primero actividad y después accesos, en lotes acotados."""
        value = self.env['ir.config_parameter'].sudo().get_param(
            'rms_portal_access_log.retention_days', '365',
        )
        try:
            days = int(value)
        except (TypeError, ValueError):
            days = 365
        if days <= 0:
            days = 365
        cutoff = fields.Datetime.now() - timedelta(days=days)
        for model, date_field in (
            ('rms.portal.activity', 'date'), ('rms.portal.access.log', 'login_date'),
        ):
            records = self.env[model].sudo()
            while batch := records.search([(date_field, '<', cutoff)], limit=1000):
                batch.unlink()
