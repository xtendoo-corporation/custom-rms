from odoo import _, models
from odoo.exceptions import AccessError
from odoo.addons.rms_ventas_restriccion_comerciales.models.restrictions import (
    lock_prices_and_taxes,
)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def action_open_reward_wizard(self):
        self.ensure_one()
        self._update_programs_and_rewards()
        action = self.env['ir.actions.actions']._for_xml_id(
            'sale_loyalty.sale_loyalty_reward_wizard_action',
        )
        action['name'] = 'Promociones disponibles'
        action['context'] = dict(self.env.context, active_id=self.id, default_order_id=self.id)
        # El asistente se crea ya con sus líneas: el cliente web no envía los
        # campos de solo lectura (la recompensa) de líneas creadas por defecto.
        action['res_id'] = self.env['sale.loyalty.reward.wizard'].create({'order_id': self.id}).id
        return action

    def _write_vals_from_reward_vals(self, reward_vals, old_lines, delete=True):
        if not self.env.su and lock_prices_and_taxes(self.env):
            self.check_access('write')
            if not old_lines.order_id <= self:
                raise AccessError(_('Reward lines must belong to this order.'))
            # sudo: el motor de promociones fija el 100 %; el comercial no puede
            # escribir descuentos. Solo elevamos la escritura de recompensas.
            return super(SaleOrder, self.sudo())._write_vals_from_reward_vals(
                reward_vals, old_lines.sudo(), delete=delete,
            ).with_env(self.env)
        return super()._write_vals_from_reward_vals(reward_vals, old_lines, delete=delete)

    def _get_program_timezone(self):
        self.ensure_one()
        # sudo: el comercial puede no tener acceso al contacto de la compañía.
        return (
            self.sudo().company_id.partner_id.tz
            or self.env['ir.config_parameter'].sudo().get_param('loyalty.timezone', 'UTC')
        )
