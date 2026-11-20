import json

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError


class ResPartner(models.Model):
    _inherit = 'res.partner'

    rms_sat_pay_later = fields.Boolean(string='Puede pagar la reparación después')
    rms_sat_no_risk_limit = fields.Boolean(string='Sin límite ni riesgo (decisión de Dirección)')
    rms_sat_can_edit_risk = fields.Boolean(compute='_compute_rms_sat_can_edit_risk')

    @api.model
    def _commercial_fields(self):
        return super()._commercial_fields() + ['rms_sat_pay_later', 'rms_sat_no_risk_limit']

    @api.depends_context('uid')
    def _compute_rms_sat_can_edit_risk(self):
        allowed = self.env.user.has_group('account_financial_risk.group_account_financial_risk_manager') or self.env.user.has_group('base.group_system')
        for partner in self:
            partner.rms_sat_can_edit_risk = allowed

    def _rms_check_risk_edit(self, vals):
        if {'rms_sat_pay_later', 'rms_sat_no_risk_limit'}.intersection(vals) and not (
                self.env.su or self.env.user.has_group('base.group_system') or
                self.env.user.has_group('account_financial_risk.group_account_financial_risk_manager')):
            raise AccessError('Solo Dirección puede cambiar las condiciones de pago del SAT.')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if any(vals.get(key) for key in ('rms_sat_pay_later', 'rms_sat_no_risk_limit')):
                self._rms_check_risk_edit(vals)
        return super().create(vals_list)

    def write(self, vals):
        # La sincronización comercial de Odoo propaga los valores a contactos hijos.
        self._rms_check_risk_edit(vals)
        return super().write(vals)


class RepairPayment(models.Model):
    _inherit = 'repair.order'

    rms_risk_percentage = fields.Float(string='Riesgo (%)', compute='_compute_rms_payment')
    rms_risk_limit = fields.Monetary(string='Límite de riesgo', currency_field='rms_currency_id', compute='_compute_rms_payment')
    rms_has_risk_limit = fields.Boolean(compute='_compute_rms_payment')
    rms_risk_exception = fields.Boolean(string='Riesgo excedido', compute='_compute_rms_payment')
    rms_paid = fields.Boolean(string='Cobrado', compute='_compute_rms_payment')
    rms_payment_exempt = fields.Boolean(string='Puede pagar después', compute='_compute_rms_payment')
    rms_payment_exempt_reason = fields.Char(string='Motivo', compute='_compute_rms_payment')
    rms_payment_forced = fields.Boolean(string='Autorizado sin cobro', copy=False, tracking=True, readonly=True)

    @api.depends('partner_id', 'sale_order_id', 'sale_order_id.amount_total',
                 'sale_order_id.invoice_ids.payment_state', 'sale_order_id.invoice_ids.state',
                 'sale_order_id.invoice_ids.amount_total', 'under_warranty', 'rms_owner_type')
    def _compute_rms_payment(self):
        for repair in self:
            partner = repair.partner_id.commercial_partner_id.sudo().with_company(repair.company_id)
            limit = partner.credit_limit if partner else 0
            exception = bool(partner.risk_exception) if partner else False
            repair.rms_has_risk_limit = bool(limit)
            repair.rms_risk_limit = limit
            repair.rms_risk_percentage = partner.risk_total * 100 / limit if limit else 0
            repair.rms_risk_exception = exception
            no_limit = bool(partner.rms_sat_no_risk_limit)
            later = bool(partner.rms_sat_pay_later and not exception)
            repair.rms_payment_exempt = no_limit or later
            repair.rms_payment_exempt_reason = 'Sin límite ni riesgo' if no_limit else ('Pago posterior autorizado' if later else '')
            order = repair.sale_order_id
            total = order.amount_total if order else 0
            invoices = order.invoice_ids.filtered(lambda inv: inv.state == 'posted' and inv.move_type in ('out_invoice', 'out_refund')) if order else self.env['account.move']
            billed = sum(inv.amount_total * (1 if inv.move_type == 'out_invoice' else -1) for inv in invoices)
            repair.rms_paid = bool(not order or order.currency_id.is_zero(total) or (
                invoices and all(inv.payment_state in ('paid', 'in_payment') for inv in invoices)
                and order.currency_id.compare_amounts(billed, total) >= 0))

    def _rms_admin_users(self):
        raw = self.env['ir.config_parameter'].sudo().get_param('rms_repair_sat.admin_user_ids', '[]')
        try:
            ids = json.loads(raw)
            ids = [int(i) for i in ids] if isinstance(ids, list) else []
        except (ValueError, TypeError):
            ids = []
        return self.env['res.users'].sudo().browse(ids).exists().filtered('active')

    def _rms_payment_blocked(self):
        self.ensure_one()
        return not (self.rms_owner_type == 'company' or self.under_warranty or self.rms_paid or self.rms_payment_exempt)

    def _rms_check_payment(self):
        for repair in self:
            if repair._rms_payment_blocked() and not repair.rms_payment_forced:
                raise UserError('Falta el cobro: cobra la reparación o pide autorización al responsable SAT.')

    def _rms_consume_payment_force(self):
        forced = self.filtered('rms_payment_forced')
        if forced:
            super(RepairPayment, forced).write({'rms_payment_forced': False})

    def write(self, vals):
        if 'rms_payment_forced' in vals and not self.env.su and not self.env.user.has_group('rms_repair_sat.group_sat_manager'):
            raise AccessError('Solo un responsable SAT puede autorizar sin cobro.')
        return super().write(vals)

    def action_rms_force_payment(self):
        if not self.env.user.has_group('rms_repair_sat.group_sat_manager'):
            raise AccessError('Solo un responsable SAT puede autorizar sin cobro.')
        self.write({'rms_payment_forced': True})
        for repair in self:
            repair.message_post(body='Autorizado sin cobro por %s.' % self.env.user.display_name)

    def action_repair_start(self):
        self._rms_check_payment()
        result = super().action_repair_start()
        self._rms_consume_payment_force()
        return result

    def action_rms_deliver(self):
        self._rms_check_payment()
        result = super().action_rms_deliver()
        self._rms_consume_payment_force()
        return result

    def _rms_schedule_admin_activity(self, kind):
        todo = self.env.ref('mail.mail_activity_data_todo')
        for repair in self:
            summary = ('Cobrar la reparación %s antes de empezar' if kind == 'payment' else 'Facturar la reparación %s') % repair.name
            users = repair._rms_admin_users() or repair.user_id or self.env.user
            for user in users:
                existing = self.env['mail.activity'].sudo().search_count([
                    ('res_model', '=', 'repair.order'), ('res_id', '=', repair.id), ('activity_type_id', '=', todo.id),
                    ('user_id', '=', user.id), ('summary', '=', summary)])
                if not existing:
                    repair.activity_schedule('mail.mail_activity_data_todo', user_id=user.id,
                                             summary=summary, date_deadline=fields.Date.context_today(repair))

    def action_repair_done(self):
        result = super().action_repair_done()
        self.filtered(lambda r: r.rms_owner_type == 'customer' and r.rms_payment_exempt and not r.rms_paid)._rms_schedule_admin_activity('invoice')
        return result


class SaleOrderPayment(models.Model):
    _inherit = 'sale.order'

    def action_confirm(self):
        result = super().action_confirm()
        repairs = self.env['repair.order'].search([('sale_order_id', 'in', self.ids)])
        repairs.filtered(lambda r: r._rms_payment_blocked())._rms_schedule_admin_activity('payment')
        return result


class SatSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    rms_sat_admin_user_ids = fields.Many2many('res.users', string='Avisos de Administración para')

    def get_values(self):
        values = super().get_values()
        raw = self.env['ir.config_parameter'].sudo().get_param('rms_repair_sat.admin_user_ids', '[]')
        try:
            ids = json.loads(raw)
        except (ValueError, TypeError):
            ids = []
        values['rms_sat_admin_user_ids'] = [(6, 0, ids if isinstance(ids, list) else [])]
        return values

    def set_values(self):
        super().set_values()
        self.env['ir.config_parameter'].sudo().set_param('rms_repair_sat.admin_user_ids', json.dumps(self.rms_sat_admin_user_ids.ids))
