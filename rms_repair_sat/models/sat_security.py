"""Control de los niveles SAT también para llamadas RPC y asistentes."""
from odoo import api, models
from odoo.exceptions import AccessError


def _require(env, level):
    if not env.user.has_group('rms_repair_sat.group_sat_' + level):
        raise AccessError('No tienes permiso para realizar esta operación del SAT.')


class ResUsers(models.Model):
    _inherit = 'res.users'

    def rms_sat_visible_partner_ids(self):
        self.ensure_one()
        # Usa las reglas de contactos efectivas de este usuario, incluidas las
        # personalizadas de la base, sin reproducir una cartera distinta.
        commercial = self.env.ref('custom.comerciales', raise_if_not_found=False)
        partner_model = self.env['ir.model'].sudo()._get('res.partner')
        rules = self.env['ir.rule'].sudo().search([('model_id', '=', partner_model.id), ('active', '=', True)])
        has_portfolio_rule = bool(commercial and rules.filtered(lambda rule: commercial in rule.groups))
        domain = [] if has_portfolio_rule else [('commercial_partner_id.user_id', '=', self.id)]
        return self.env['res.partner'].with_user(self).search(domain).ids


class RepairOrderSecurity(models.Model):
    _inherit = 'repair.order'

    def _rms_check_sat_access(self, level):
        _require(self.env, level)

    def _rms_readonly_commercial(self):
        group = self.env.ref('custom.comerciales', raise_if_not_found=False)
        return bool(group and self.env.user in group.all_user_ids and
                    not self.env.user.has_group('rms_repair_sat.group_sat_warehouse') and
                    not self.env.user.has_group('base.group_system'))

    @api.model_create_multi
    def create(self, vals_list):
        if self._rms_readonly_commercial():
            raise AccessError('Los comerciales solo pueden consultar reparaciones.')
        return super().create(vals_list)

    def write(self, vals):
        if self._rms_readonly_commercial():
            raise AccessError('Los comerciales solo pueden consultar reparaciones.')
        return super().write(vals)

    def unlink(self):
        if self._rms_readonly_commercial():
            raise AccessError('Los comerciales solo pueden consultar reparaciones.')
        return super().unlink()

    def action_rms_register_entry(self):
        _require(self.env, 'warehouse')
        return super().action_rms_register_entry()

    def action_rms_deliver(self):
        _require(self.env, 'warehouse')
        return super().action_rms_deliver()

    def action_rms_print_label(self):
        _require(self.env, 'warehouse')
        return super().action_rms_print_label()

    def action_validate(self):
        _require(self.env, 'technician')
        return super().action_validate()

    def action_assign(self):
        _require(self.env, 'technician')
        return super().action_assign()

    def action_unreserve(self):
        _require(self.env, 'technician')
        return super().action_unreserve()

    def action_repair_cancel(self):
        _require(self.env, 'technician')
        return super().action_repair_cancel()

    def action_repair_cancel_draft(self):
        _require(self.env, 'technician')
        return super().action_repair_cancel_draft()

    def action_generate_serial(self):
        _require(self.env, 'technician')
        return super().action_generate_serial()

    def action_repair_start(self):
        _require(self.env, 'technician')
        return super().action_repair_start()

    def action_repair_end(self):
        _require(self.env, 'technician')
        return super().action_repair_end()

    def action_repair_done(self):
        _require(self.env, 'technician')
        return super().action_repair_done()

    def action_create_sale_order(self):
        _require(self.env, 'technician')
        return super().action_create_sale_order()

    def action_assign(self):
        _require(self.env, 'technician')
        return super().action_assign()

    def action_unreserve(self):
        _require(self.env, 'technician')
        return super().action_unreserve()

    def action_repair_cancel(self):
        _require(self.env, 'technician')
        return super().action_repair_cancel()

    def action_repair_cancel_draft(self):
        _require(self.env, 'technician')
        return super().action_repair_cancel_draft()

    def action_generate_serial(self):
        _require(self.env, 'technician')
        return super().action_generate_serial()

    def action_rms_send_factory(self):
        _require(self.env, 'technician')
        return super().action_rms_send_factory()

    def action_rms_back_from_factory(self):
        _require(self.env, 'technician')
        return super().action_rms_back_from_factory()

    def action_rms_swap(self):
        _require(self.env, 'technician')
        return super().action_rms_swap()

    def action_rms_wait_part(self):
        _require(self.env, 'technician')
        return super().action_rms_wait_part()

    def action_rms_part_received(self):
        _require(self.env, 'technician')
        return super().action_rms_part_received()

    def action_rms_add_factory_bill(self):
        _require(self.env, 'technician')
        return super().action_rms_add_factory_bill()

    def action_rms_add_labour(self):
        _require(self.env, 'technician')
        return super().action_rms_add_labour()

    def action_rms_send_quote(self):
        _require(self.env, 'technician')
        return super().action_rms_send_quote()

    def action_rms_reject_quote(self):
        _require(self.env, 'technician')
        return super().action_rms_reject_quote()

    def action_rms_reapprove(self):
        _require(self.env, 'technician')
        return super().action_rms_reapprove()

    def action_rms_add_used_alternative(self):
        _require(self.env, 'technician')
        return super().action_rms_add_used_alternative()

    def action_rms_choose_used(self):
        _require(self.env, 'technician')
        return super().action_rms_choose_used()

    def action_rms_choose_new(self):
        _require(self.env, 'technician')
        return super().action_rms_choose_new()


class DisassemblySecurity(models.Model):
    _inherit = 'rms.disassembly'

    def action_done(self):
        _require(self.env, 'manager')
        return super().action_done()
