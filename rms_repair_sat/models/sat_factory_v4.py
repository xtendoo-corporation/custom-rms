from odoo import api, fields, models
from odoo.exceptions import UserError


class RepairOrderFactoryV4(models.Model):
    _inherit = 'repair.order'

    rms_factory_result = fields.Selection(selection_add=[
        ('warranty_rejected', 'Garantía rechazada por la fábrica'),
        ('destroyed', 'Destruido por indicación de fábrica'),
    ], ondelete={'warranty_rejected': 'set null', 'destroyed': 'set null'})
    rms_warranty_rejected = fields.Boolean(string='Garantía rechazada', copy=False, readonly=True, tracking=True)
    rms_warranty_rejected_date = fields.Date(string='Fecha de rechazo de garantía', copy=False, readonly=True)
    rms_warranty_rejected_reason = fields.Text(string='Motivo del rechazo de garantía', copy=False, readonly=True)
    rms_destroyed_date = fields.Date(string='Fecha de destrucción', copy=False, readonly=True)
    rms_destroyed_authorization_ref = fields.Char(string='Autorización de destrucción', copy=False, readonly=True)
    rms_destroyed_note = fields.Text(string='Nota de destrucción', copy=False, readonly=True)
    rms_destroyed_move_id = fields.Many2one('stock.move', string='Movimiento de destrucción', copy=False, readonly=True)

    rms_physically_at_factory = fields.Boolean(string='Equipo en fábrica', compute='_compute_rms_physically_at_factory')

    @api.depends('lot_id', 'rms_site', 'rms_owner_type', 'rms_stage', 'partner_id')
    def _compute_rms_physically_at_factory(self):
        for repair in self:
            warehouse = repair._rms_warehouse() if repair.rms_site else self.env['stock.warehouse']
            owner = repair.partner_id.id if repair.rms_owner_type == 'customer' else False
            repair.rms_physically_at_factory = bool(warehouse and repair.lot_id and
                self.env['stock.quant'].sudo().search_count([
                    ('product_id', '=', repair.product_id.id), ('lot_id', '=', repair.lot_id.id),
                    ('owner_id', '=', owner), ('location_id', '=', warehouse.rms_sat_factory_location_id.id),
                    ('quantity', '>', 0)]))

    def action_rms_send_factory(self):
        if any(repair.rms_physically_at_factory for repair in self):
            raise UserError('El equipo sigue en fábrica.')
        return super().action_rms_send_factory()

    def _rms_send_to_factory(self, *args, **kwargs):
        if any(repair.rms_physically_at_factory for repair in self):
            raise UserError('El equipo sigue en fábrica.')
        return super()._rms_send_to_factory(*args, **kwargs)

    def action_rms_deliver(self):
        if any(repair.rms_physically_at_factory for repair in self):
            raise UserError('El equipo sigue en fábrica.')
        return super().action_rms_deliver()

    def action_rms_warranty_rejected(self):
        self.ensure_one()
        self._rms_check_sat_access('technician')
        if not self.under_warranty:
            raise UserError('El equipo no está marcado en garantía.')
        return {'type': 'ir.actions.act_window', 'name': 'Garantía rechazada',
                'res_model': 'rms.repair.warranty.reject.wizard', 'view_mode': 'form', 'target': 'new',
                'context': {'default_repair_id': self.id}}

    def _rms_reject_warranty(self, reason):
        self.ensure_one()
        self._rms_check_sat_access('technician')
        if not (reason or '').strip():
            raise UserError('Indica el motivo del rechazo de garantía.')
        self.write({'under_warranty': False, 'rms_warranty_rejected': True,
                    'rms_warranty_rejected_date': fields.Date.context_today(self),
                    'rms_warranty_rejected_reason': reason.strip(), 'rms_stage': 'diagnosis'})
        self.message_post(body='La fábrica ha rechazado la garantía. Motivo: %s' % reason.strip())
        group = self.env.ref('rms_repair_sat.group_sat_manager')
        managers = group.all_user_ids.filtered(lambda user: user.active and not user.share)
        responsible = self.user_id or managers
        self._rms_factory_activity(responsible, 'Hacer presupuesto: la fábrica ha rechazado la garantía')
        if self.rms_swap_done:
            self._rms_factory_activity(managers, 'Garantía rechazada tras un cambio en garantía: decidir si se factura al cliente la unidad entregada (%s)' % (self.rms_swap_lot_id.name or ''))

    def _rms_factory_activity(self, users, summary):
        self.ensure_one()
        todo = self.env.ref('mail.mail_activity_data_todo')
        for user in users:
            exists = self.env['mail.activity'].sudo().search_count([
                ('res_model', '=', 'repair.order'), ('res_id', '=', self.id), ('activity_type_id', '=', todo.id),
                ('user_id', '=', user.id), ('summary', '=', summary)])
            if not exists:
                self.activity_schedule('mail.mail_activity_data_todo', user_id=user.id,
                                       summary=summary, date_deadline=fields.Date.context_today(self))

    def action_rms_destroy_factory(self):
        self.ensure_one()
        self._rms_check_sat_access('technician')
        self._rms_check_destroy_owner()
        return {'type': 'ir.actions.act_window', 'name': 'Destruir (indicación de fábrica)',
                'res_model': 'rms.repair.destroy.wizard', 'view_mode': 'form', 'target': 'new',
                'context': {'default_repair_id': self.id}}

    def _rms_check_destroy_owner(self):
        self.ensure_one()
        if self.rms_owner_type != 'company':
            raise UserError('Solo se destruyen unidades nuestras (RA). Si el equipo es del cliente, haz antes el cambio en garantía.')

    def _rms_destroy_factory(self, authorization_ref, note=False, location=False):
        self.ensure_one()
        self._rms_check_sat_access('technician')
        self._rms_check_destroy_owner()
        if not (authorization_ref or '').strip():
            raise UserError('Indica la autorización de destrucción.')
        if not self.rms_in_sat or not self.lot_id:
            raise UserError('El equipo no está registrado en el SAT o no tiene nº de serie.')
        warehouse = self._rms_sat_locations()
        allowed = warehouse.rms_sat_location_id | warehouse.rms_ra_location_id | warehouse.rms_sat_factory_location_id
        if location:
            allowed &= location
        quant = self.env['stock.quant'].sudo().search([
            ('product_id', '=', self.product_id.id), ('lot_id', '=', self.lot_id.id),
            ('location_id', 'in', allowed.ids), ('owner_id', '=', False), ('quantity', '>', 0)], limit=1)
        if not quant or quant.quantity < (self.product_qty or 1):
            raise UserError('No se encuentra el equipo nuestro en SAT, RA o fábrica.')
        scrap = self.env['stock.location'].sudo().search([
            ('usage', '=', 'inventory'), ('company_id', '=', self.company_id.id),
            ('rms_disassembly', '=', False)], order='id', limit=1)
        if not scrap:
            scrap = self.env['stock.location'].sudo().search([('usage', '=', 'inventory'),
                ('company_id', '=', False), ('rms_disassembly', '=', False)], order='id', limit=1)
        if not scrap:
            raise UserError('Falta una ubicación de desecho para la empresa.')
        move = self._rms_customer_move(quant.location_id, scrap, 'Destrucción por fábrica')
        self.write({'rms_factory_result': 'destroyed', 'rms_destroyed_date': fields.Date.context_today(self),
                    'rms_destroyed_authorization_ref': authorization_ref.strip(), 'rms_destroyed_note': note,
                    'rms_destroyed_move_id': move.id, 'rms_in_sat': False, 'rms_stage': 'delivered',
                    'rms_factory_back_date': fields.Date.context_today(self) if quant.location_id == warehouse.rms_sat_factory_location_id else self.rms_factory_back_date})
        self.message_post(body='Destruido por indicación de fábrica. Autorización: %s. %s' % (authorization_ref.strip(), note or ''))
        return move
