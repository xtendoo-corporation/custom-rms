from datetime import timedelta

from odoo import api, fields, models
from odoo.fields import Domain

from .repair_order import SAT_STAGES


class RepairStageLog(models.Model):
    _name = 'rms.repair.stage.log'
    _description = 'Historial de fases SAT'
    _order = 'date_in desc, id desc'

    repair_id = fields.Many2one('repair.order', string='Reparación', required=True, index=True, ondelete='cascade')
    stage = fields.Selection(SAT_STAGES + [('cancel', 'Cancelado')], string='Fase', required=True, index=True)
    date_in = fields.Datetime(string='Entrada en fase', required=True, index=True)
    date_out = fields.Datetime(string='Salida de fase')
    days = fields.Float(string='Días', compute='_compute_days', store=True, aggregator='avg')
    user_id = fields.Many2one('res.users', string='Usuario', required=True, default=lambda self: self.env.user)
    site = fields.Selection(related='repair_id.rms_site', string='Sede', store=True, index=True)
    company_id = fields.Many2one(related='repair_id.company_id', string='Empresa', store=True, index=True)

    @api.depends('date_in', 'date_out')
    def _compute_days(self):
        now = fields.Datetime.now()
        for log in self:
            log.days = max(((log.date_out or now) - log.date_in).total_seconds() / 86400, 0) if log.date_in else 0


class RepairOrderPanel(models.Model):
    _inherit = 'repair.order'

    rms_stage_log_ids = fields.One2many('rms.repair.stage.log', 'repair_id', string='Historial de fases')
    rms_amount_invoiced = fields.Monetary(string='Facturado', currency_field='rms_currency_id', readonly=True, copy=False, groups='rms_repair_sat.group_sat_manager')
    rms_parts_cost = fields.Monetary(string='Coste de piezas', currency_field='rms_currency_id', readonly=True, copy=False, groups='rms_repair_sat.group_sat_manager')
    rms_margin = fields.Monetary(string='Margen', currency_field='rms_currency_id', readonly=True, copy=False, groups='rms_repair_sat.group_sat_manager')
    rms_close_date = fields.Date(string='Fecha de entrega', readonly=True, copy=False, index=True)
    rms_lead_days = fields.Float(string='Días hasta entrega', readonly=True, copy=False, aggregator='avg')
    rms_late = fields.Boolean(search='_search_rms_late')

    @api.model
    def _search_rms_late(self, operator, value):
        # El cálculo usa días completos y marca solo al superar el límite.
        if operator not in ('=', '!='):
            return NotImplemented
        now = fields.Datetime.now()
        domains = []
        for limit in self.env['rms.repair.stage.limit'].sudo().search([('days', '>', 0)]):
            domains.append([('rms_stage', '=', limit.stage),
                            ('rms_stage_date', '<=', now - timedelta(days=limit.days + 1))])
        late = Domain.OR(domains)
        positive = bool(value) == (operator == '=')
        return late if positive else ~late

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._rms_sync_stage_log()
        return records

    def write(self, vals):
        before = {repair.id: repair.rms_stage for repair in self}
        result = super().write(vals)
        changed = self.filtered(lambda repair: before.get(repair.id) != repair.rms_stage)
        if changed:
            changed._rms_sync_stage_log()
        if changed or 'rms_entry_date' in vals:
            self._rms_refresh_lead_days()
        return result

    def _rms_sync_stage_log(self):
        """Captura también la fase que Odoo cambia indirectamente al cambiar state."""
        Log = self.env['rms.repair.stage.log'].sudo()
        for repair in self:
            open_logs = Log.search([('repair_id', '=', repair.id), ('date_out', '=', False)], order='date_in desc, id desc')
            current = open_logs[:1]
            if current and current.stage == repair.rms_stage:
                if len(open_logs) > 1:
                    (open_logs - current).write({'date_out': current.date_in})
                continue
            moment = repair.rms_stage_date or fields.Datetime.now()
            if open_logs:
                open_logs.write({'date_out': moment})
            Log.create({'repair_id': repair.id, 'stage': repair.rms_stage, 'date_in': moment,
                        'user_id': self.env.user.id})
            if repair.rms_stage == 'delivered':
                # Evita volver a ejecutar write de reparación solo por un dato técnico.
                super(RepairOrderPanel, repair).write({'rms_close_date': fields.Date.to_date(moment)})

    def _rms_refresh_lead_days(self):
        for repair in self:
            end = repair.rms_close_date
            days = max((end - fields.Date.to_date(repair.rms_entry_date)).days, 0) if end and repair.rms_entry_date else 0
            if repair.rms_lead_days != days:
                super(RepairOrderPanel, repair).write({'rms_lead_days': days})

    def _rms_refresh_panel_amounts(self):
        """Recalcula por reparación; se ejecuta a diario para incluir facturas y ajustes posteriores."""
        for repair in self:
            invoices = repair.sale_order_id.invoice_ids.filtered(
                lambda move: move.state == 'posted' and move.move_type in ('out_invoice', 'out_refund'))
            # Los valores del panel se expresan en la moneda de la empresa de la reparación.
            invoiced = sum((1 if invoice.move_type == 'out_invoice' else -1) *
                           invoice.currency_id._convert(invoice.amount_untaxed, repair.rms_currency_id,
                                                        repair.company_id, invoice.invoice_date or fields.Date.context_today(repair))
                           for invoice in invoices)
            parts = repair.move_ids.filtered(lambda move: move.state == 'done' and move.repair_line_type == 'add')
            cost = sum(parts.mapped('value'))
            super(RepairOrderPanel, repair).write({'rms_amount_invoiced': invoiced,
                'rms_parts_cost': cost, 'rms_margin': invoiced - cost})
        self._rms_refresh_lead_days()

    @api.model
    def _rms_initialize_panel(self):
        # No duplicar registros al repetir una migración interrumpida.
        repairs = self.sudo().search([])
        for repair in repairs:
            if not repair.rms_stage_log_ids:
                repair._rms_sync_stage_log()
            if repair.rms_stage == 'delivered' and not repair.rms_close_date:
                super(RepairOrderPanel, repair).write({
                    'rms_close_date': fields.Date.to_date(repair.rms_stage_date or repair.create_date)})
        self._cron_rms_panel()

    @api.model
    def _cron_rms_panel(self):
        repairs = self.sudo().search([])
        for start in range(0, len(repairs), 500):
            repairs[start:start + 500]._rms_refresh_panel_amounts()
        self.env['rms.repair.stage.log'].sudo().search([('date_out', '=', False)])._compute_days()


class StockQuantPanel(models.Model):
    _inherit = 'stock.quant'

    @api.model
    def action_rms_ra_quants(self):
        warehouses = self.env['stock.warehouse'].sudo().search([('rms_ra_location_id', '!=', False)])
        return {
            'type': 'ir.actions.act_window', 'name': 'Unidades en RA', 'res_model': 'stock.quant',
            'view_mode': 'list', 'views': [(self.env.ref('rms_repair_sat.view_rms_ra_quant_list').id, 'list')],
            'domain': [('location_id', 'child_of', warehouses.mapped('rms_ra_location_id').ids), ('quantity', '>', 0)],
            'context': {'create': False},
        }
