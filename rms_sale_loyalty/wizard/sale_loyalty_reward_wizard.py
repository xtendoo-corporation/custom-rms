from odoo import api, fields, models, Command
from odoo.exceptions import UserError, ValidationError


class SaleLoyaltyRewardWizard(models.TransientModel):
    _inherit = 'sale.loyalty.reward.wizard'

    line_ids = fields.One2many(
        'rms.sale.loyalty.reward.wizard.line', 'wizard_id',
        string='Promociones',
    )

    @api.model
    def _lines_for_order(self, order):
        if not order:
            return []
        order._update_programs_and_rewards()
        rewards = self.env['loyalty.reward']
        for claimable in order._get_claimable_rewards().values():
            rewards |= claimable
        return [Command.create({
            'reward_id': reward.id,
            'selected_product_id': reward.reward_product_ids[:1].id
                if reward.reward_type == 'product' else False,
        }) for reward in rewards]

    @api.model_create_multi
    def create(self, vals_list):
        prepared = []
        for vals in vals_list:
            vals = dict(vals)
            if 'line_ids' not in vals:
                order_id = vals.get('order_id') or self.env.context.get('default_order_id') or self.env.context.get('active_id')
                vals['line_ids'] = self._lines_for_order(self.env['sale.order'].browse(order_id))
            prepared.append(vals)
        return super().create(prepared)

    def action_apply(self):
        self.ensure_one()
        selected = self.line_ids.filtered('selected')
        if not selected:
            raise ValidationError('Selecciona al menos una promoción.')
        for line in selected:
            coupon = next((coupon for coupon, rewards in self.order_id._get_claimable_rewards().items()
                           if line.reward_id in rewards), False)
            if not coupon:
                raise UserError('%s: la recompensa ya no es reclamable.' % line.program_id.name)
            if line.multi_product and line.selected_product_id not in line.reward_product_ids:
                raise UserError('%s: selecciona un producto válido para la recompensa.' % line.program_id.name)
            try:
                result = self.order_id._apply_program_reward(
                    line.reward_id, coupon, product=line.selected_product_id,
                )
            except UserError as error:
                raise UserError('%s: %s' % (line.program_id.name, error)) from error
            if result.get('error'):
                raise UserError('%s: %s' % (line.program_id.name, result['error']))
        self.order_id._update_programs_and_rewards()
        self._unlink_unused_coupon_ids()
        return True


class SaleLoyaltyRewardWizardLine(models.TransientModel):
    _name = 'rms.sale.loyalty.reward.wizard.line'
    _description = 'Selección de promoción disponible'

    wizard_id = fields.Many2one('sale.loyalty.reward.wizard', required=True, ondelete='cascade')
    reward_id = fields.Many2one('loyalty.reward', required=True, readonly=True)
    program_id = fields.Many2one(related='reward_id.program_id')
    program_name = fields.Char(related='program_id.name', string='Promoción')
    reward_description = fields.Char(related='reward_id.description', string='Recompensa')
    internal_note = fields.Text(related='program_id.rms_internal_note', string='Nota interna')
    selected = fields.Boolean(string='Seleccionar')
    multi_product = fields.Boolean(related='reward_id.multi_product')
    reward_product_ids = fields.Many2many(related='reward_id.reward_product_ids')
    selected_product_id = fields.Many2one(
        'product.product', string='Producto',
        domain="[('id', 'in', reward_product_ids)]",
        compute='_compute_selected_product_id', store=True, readonly=False,
    )

    @api.depends('reward_product_ids')
    def _compute_selected_product_id(self):
        for line in self:
            line.selected_product_id = line.reward_product_ids[:1]

