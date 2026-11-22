import logging

import psycopg2

from odoo import _, api, fields, models
from odoo.exceptions import ConcurrencyError, UserError

_logger = logging.getLogger(__name__)

_CLIENT_UID_INDEX = 'rms_delivery_scan_picking_client_uid_uniq'

RESULTS = [
    ('ok', 'Correcto'),
    ('amber', 'Necesita administrador'),
    ('red', 'Bloqueado'),
    ('grey', 'Código de producto'),
    ('duplicate', 'Ya leído'),
]
REASONS = [
    ('ok', 'Correcto'),
    ('state_mismatch', 'Estado distinto al pedido'),
    ('serial_mismatch', 'Nº de serie distinto al fijado en el pedido'),
    ('pack_incomplete', 'Paquete de 2ª mano incompleto'),
    ('used_no_pack', '2ª mano sin paquete autorizado'),
    ('demo_sale', 'Demo: no se vende'),
    ('not_in_picking', 'No está en este albarán'),
    ('not_in_deposit', 'No consta en este depósito'),
    ('not_in_stock', 'No está en stock en el origen'),
    ('already_out', 'Ya salió'),
    ('reserved_other', 'Reservado en otro albarán'),
    ('over_qty', 'Sobra: ya están todas leídas'),
    ('unknown', 'Nº de serie desconocido'),
    ('product_code', 'Código de producto / EAN'),
    ('already_read', 'Ya leído'),
]
APPROVALS = [
    ('none', 'No necesita'),
    ('pending', 'Pendiente'),
    ('approved', 'Aprobado'),
    ('rejected', 'Rechazado'),
]


class RmsDeliveryScan(models.Model):
    """Una lectura de la pistola en un checklist. No se borra nunca: deshacer
    solo la marca como deshecha."""

    _name = 'rms.delivery.scan'
    _description = 'Lectura de checklist de salida'
    _order = 'scanned_at desc, id desc'
    _rec_name = 'code'

    picking_id = fields.Many2one(
        'stock.picking', string='Albarán', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='picking_id.company_id', store=True, string='Empresa')
    partner_id = fields.Many2one(related='picking_id.partner_id', store=True, string='Cliente')
    kind = fields.Selection(related='picking_id.rms_check_kind', store=True, string='Tipo')
    code = fields.Char(string='Leído', required=True)
    code_clean = fields.Char(string='Código')
    user_id = fields.Many2one('res.users', string='Operario', required=True, default=lambda self: self.env.user)
    scanned_at = fields.Datetime(string='Fecha y hora', required=True, default=fields.Datetime.now)
    lot_id = fields.Many2one('stock.lot', string='Nº de serie', index=True)
    product_id = fields.Many2one('product.product', string='Producto')
    move_id = fields.Many2one('stock.move', string='Línea del albarán', ondelete='set null')
    state_id = fields.Many2one('product.state', string='Estado del equipo')
    pack_id = fields.Many2one('rms.used.pack', string='Paquete de 2ª mano')
    result = fields.Selection(RESULTS, string='Resultado', required=True, index=True)
    reason = fields.Selection(REASONS, string='Motivo', required=True)
    message = fields.Char(string='Explicación')
    needs_review = fields.Boolean(string='Hay que revisarlo')
    reviewed = fields.Boolean(string='Revisado')
    reviewed_by_id = fields.Many2one('res.users', string='Revisado por')
    reviewed_at = fields.Datetime(string='Revisado el')
    approval_state = fields.Selection(APPROVALS, string='Aprobación', default='none', required=True)
    approved_by_id = fields.Many2one('res.users', string='Decidido por')
    approved_at = fields.Datetime(string='Decidido el')
    approval_note = fields.Char(string='Nota del administrador')
    undone = fields.Boolean(string='Deshecha')
    undone_by_id = fields.Many2one('res.users', string='Deshecha por')
    undone_at = fields.Datetime(string='Deshecha el')
    is_incident = fields.Boolean(string='Incidencia', index=True)
    incident_resolved = fields.Boolean(string='Incidencia resuelta')
    incident_resolved_by_id = fields.Many2one('res.users', string='Resuelta por')
    incident_note = fields.Char(string='Nota de la incidencia')
    client_uid = fields.Char(
        string='Id. de lectura en el dispositivo', readonly=True, copy=False, index=True,
        help="Evita duplicar una lectura si el aparato la reenvía tras perder la conexión.")

    def init(self):
        """Índice único parcial (picking_id, client_uid): la misma lectura
        reenviada no puede guardarse dos veces. A mano, para que solo afecte a
        las lecturas que traen identificador."""
        cr = self.env.cr
        cr.execute("SELECT 1 FROM pg_indexes WHERE indexname = %s", (_CLIENT_UID_INDEX,))
        if cr.fetchone():
            return
        cr.execute("""
            SELECT 1 FROM rms_delivery_scan WHERE client_uid IS NOT NULL
             GROUP BY picking_id, client_uid HAVING count(*) > 1 LIMIT 1
        """)
        if cr.fetchone():
            _logger.warning(
                "rms_delivery_scan: hay lecturas con el mismo client_uid; no se crea el índice único %s.",
                _CLIENT_UID_INDEX)
            return
        cr.execute(
            "CREATE UNIQUE INDEX %s ON rms_delivery_scan (picking_id, client_uid) "
            "WHERE client_uid IS NOT NULL" % _CLIENT_UID_INDEX)

    @api.model
    def _create_scan(self, vals):
        """Crea la lectura. Si otra petición con el mismo client_uid (la misma
        lectura reenviada mientras la primera seguía en curso) se ha
        adelantado, se repite la llamada entera: en el reintento ya se ve la
        fila guardada y se contesta con su mismo veredicto."""
        if not vals.get('client_uid'):
            return self.create(vals)
        try:
            with self.env.cr.savepoint():
                return self.create(vals)
        except psycopg2.errors.UniqueViolation as exc:
            if getattr(exc.diag, 'constraint_name', '') != _CLIENT_UID_INDEX:
                raise
            raise ConcurrencyError("Lectura reenviada a la vez: %s" % vals['client_uid']) from exc

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Lo inesperado queda como incidencia aunque luego se arregle.
            if vals.get('result') in ('red', 'amber'):
                vals['is_incident'] = True
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('result') in ('red', 'amber'):
            vals = dict(vals, is_incident=True)
        return super().write(vals)

    def _counts(self):
        """La lectura cuenta como unidad que sale."""
        self.ensure_one()
        return not self.undone and (
            self.result == 'ok' or (self.result == 'amber' and self.approval_state == 'approved'))

    def _occupies(self):
        """Ocupa hueco en su línea (verde, o ámbar sin rechazar)."""
        self.ensure_one()
        return not self.undone and (
            self.result == 'ok' or (self.result == 'amber' and self.approval_state != 'rejected'))

    def action_resolve_incident(self):
        if not self.env.user.has_group('stock.group_stock_manager'):
            raise UserError(_("Solo un responsable de inventario puede cerrar una incidencia."))
        self.sudo().write({'incident_resolved': True, 'incident_resolved_by_id': self.env.uid})

    def action_open_picking(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'res_model': 'stock.picking',
            'res_id': self.picking_id.id, 'views': [[False, 'form']],
        }
