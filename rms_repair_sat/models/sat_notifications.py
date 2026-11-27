from odoo import api, fields, models
from odoo.exceptions import UserError


RETURN_SHIPPING = [
    ('invoice', 'Portes en factura'), ('collect', 'Portes debidos'),
    ('customer', 'Por cuenta del cliente'), ('hand', 'Recoge en mano'),
    ('ours', 'A nuestro cargo'),
]


class RepairOrder(models.Model):
    _inherit = 'repair.order'

    @api.model
    def _rms_default_return_shipping(self):
        value = self.env['ir.config_parameter'].sudo().get_param(
            'rms_repair_sat.default_return_shipping', 'invoice')
        return value if value in dict(RETURN_SHIPPING) else 'invoice'

    rms_return_shipping = fields.Selection(RETURN_SHIPPING, string='Envío de vuelta',
                                            default=_rms_default_return_shipping, required=True)
    rms_return_shipping_effective = fields.Selection(RETURN_SHIPPING, string='Portes de vuelta',
        compute='_compute_rms_return_shipping_effective')
    rms_shipping_line_id = fields.Many2one('sale.order.line', string='Línea de portes', copy=False, readonly=True)
    rms_ready_date = fields.Date(string='Listo desde', copy=False, readonly=True)
    rms_reminder_1_sent = fields.Boolean(string='Primer aviso enviado', copy=False, readonly=True)
    rms_reminder_2_sent = fields.Boolean(string='Segundo aviso enviado', copy=False, readonly=True)
    rms_not_collected = fields.Boolean(string='Sin recoger', copy=False, readonly=True, index=True)

    @api.depends('rms_return_shipping', 'under_warranty')
    def _compute_rms_return_shipping_effective(self):
        for repair in self:
            repair.rms_return_shipping_effective = ('ours' if repair.under_warranty and
                                                     repair.rms_return_shipping == 'invoice'
                                                     else repair.rms_return_shipping)

    def _rms_send_ready_mail(self):
        template = self.env.ref('rms_repair_sat.mail_template_sat_ready')
        for repair in self:
            recipient = repair.rms_contact_id.email or repair.partner_id.email
            if recipient:
                template.send_mail(repair.id, force_send=False, email_values={'email_to': recipient})

    def _rms_after_stage_change(self, previous):
        for repair in self:
            old = previous.get(repair.id)
            if old == repair.rms_stage:
                continue
            if repair.rms_stage in ('ready', 'uncollected'):
                values = {'rms_reminder_1_sent': False, 'rms_reminder_2_sent': False,
                          'rms_not_collected': False}
                if repair.rms_stage == 'ready':
                    values['rms_ready_date'] = fields.Date.context_today(repair)
                repair.write(values)
                if repair.rms_stage == 'ready':
                    repair._rms_send_ready_mail()

    @api.model_create_multi
    def create(self, vals_list):
        repairs = super().create(vals_list)
        repairs.filtered(lambda r: r.rms_stage == 'ready')._rms_after_stage_change({})
        return repairs

    def write(self, vals):
        before = {repair.id: repair.rms_stage for repair in self} if 'rms_stage' in vals or 'state' in vals else {}
        result = super().write(vals)
        if before:
            self._rms_after_stage_change(before)
        if 'under_warranty' in vals or 'rms_return_shipping' in vals:
            for repair in self.filtered(lambda r: r.under_warranty and r.rms_return_shipping == 'invoice'
                                        and r.rms_shipping_line_id and r.rms_shipping_line_id.price_unit):
                repair.rms_shipping_line_id.price_unit = 0.0
        return result

    def action_rms_add_shipping(self):
        self.ensure_one()
        self._rms_check_sat_access('technician')
        if self.rms_return_shipping != 'invoice':
            raise UserError('Elige portes en factura.')
        if self.under_warranty:
            raise UserError('En garantía los portes corren a cargo de RMS.')
        order = self._rms_draft_order()
        product = self.env.ref('rms_repair_sat.product_sat_shipping')
        if not self.rms_shipping_line_id or self.rms_shipping_line_id.order_id != order:
            self.rms_shipping_line_id = self.env['sale.order.line'].create({
                'order_id': order.id, 'product_id': product.id, 'product_uom_qty': 1,
                'name': product.display_name, 'price_unit': 0.0,
            })
        self.rms_shipping_line_id._rms_clear_service_discounts()
        return True

    @api.model
    def _cron_rms_pickup_reminders(self):
        params = self.env['ir.config_parameter'].sudo()
        def days(key, default):
            try:
                return max(0, int(params.get_param('rms_repair_sat.' + key, str(default))))
            except (ValueError, TypeError):
                return default
        n1, n2, n3 = (days('reminder_1_days', 30), days('reminder_2_days', 60),
                      days('reminder_3_days', 90))
        today = fields.Date.context_today(self)
        template = self.env.ref('rms_repair_sat.mail_template_sat_reminder')
        repairs = self.search([('rms_stage', 'in', ('ready', 'uncollected'))])
        for repair in repairs:
            start = repair.rms_ready_date if repair.rms_stage == 'ready' else repair.rms_rejected_date
            if not start:
                continue
            elapsed = (today - start).days
            email = repair.rms_contact_id.email or repair.partner_id.email
            changes = {}
            if elapsed >= n1 and not repair.rms_reminder_1_sent and email:
                template.send_mail(repair.id, force_send=False, email_values={'email_to': email})
                changes['rms_reminder_1_sent'] = True
            if elapsed >= n2 and not repair.rms_reminder_2_sent and email:
                template.send_mail(repair.id, force_send=False, email_values={'email_to': email})
                changes['rms_reminder_2_sent'] = True
            if elapsed >= n3 and not repair.rms_not_collected:
                group = self.env.ref('rms_repair_sat.group_sat_manager', raise_if_not_found=False)
                users = group.all_user_ids.filtered(lambda u: u.active and not u.share) if group else self.env['res.users']
                users = users or repair._rms_admin_users()
                summary = 'Equipo sin recoger %s' % repair.name
                for user in users:
                    existing = self.env['mail.activity'].search_count([
                        ('res_model', '=', 'repair.order'), ('res_id', '=', repair.id),
                        ('activity_type_id', '=', self.env.ref('mail.mail_activity_data_todo').id),
                        ('summary', '=', summary), ('user_id', '=', user.id)])
                    if not existing:
                        repair.activity_schedule('mail.mail_activity_data_todo', user_id=user.id,
                                                 date_deadline=today, summary=summary)
                changes['rms_not_collected'] = True
            if changes:
                repair.write(changes)
        return True


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    rms_sat_default_return_shipping = fields.Selection(RETURN_SHIPPING, string='Envío de vuelta por defecto',
        config_parameter='rms_repair_sat.default_return_shipping', default='invoice')
    rms_sat_reminder_1_days = fields.Integer(string='Primer aviso (días)',
        config_parameter='rms_repair_sat.reminder_1_days', default=30)
    rms_sat_reminder_2_days = fields.Integer(string='Segundo aviso (días)',
        config_parameter='rms_repair_sat.reminder_2_days', default=60)
    rms_sat_reminder_3_days = fields.Integer(string='Sin recoger (días)',
        config_parameter='rms_repair_sat.reminder_3_days', default=90)
