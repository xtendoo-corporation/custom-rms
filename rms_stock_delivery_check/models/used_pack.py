from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class RmsUsedPack(models.Model):
    _name = 'rms.used.pack'
    _description = 'Paquete de 2ª mano autorizado'
    _inherit = ['mail.thread']
    _order = 'id desc'

    name = fields.Char(string='Nombre', required=True, tracking=True)
    company_id = fields.Many2one(
        'res.company', string='Empresa', required=True, default=lambda self: self.env.company)
    lot_ids = fields.Many2many(
        'stock.lot', 'rms_used_pack_lot_rel', 'pack_id', 'lot_id', string='Equipos (nº de serie)',
        domain="[('product_state_code', '=', 'second_hand')]",
        help="Equipos de 2ª mano que se venden juntos. Un paquete puede tener un solo equipo.")
    lot_count = fields.Integer(string='Nº de equipos', compute='_compute_lot_count')
    price = fields.Monetary(string='Precio del paquete', currency_field='currency_id')
    currency_id = fields.Many2one(related='company_id.currency_id')
    active = fields.Boolean(default=True, string='Activo')
    authorized_by_id = fields.Many2one(
        'res.users', string='Autorizado por', default=lambda self: self.env.user, tracking=True)
    authorized_date = fields.Date(string='Fecha de autorización', default=fields.Date.context_today)
    state = fields.Selection([
        ('authorized', 'Autorizado (se vende entero)'),
        ('broken', 'Roto por administrador (se vende suelto)'),
        ('sold', 'Vendido'),
    ], string='Situación', default='authorized', required=True, tracking=True, copy=False)
    broken_by_id = fields.Many2one('res.users', string='Roto por', readonly=True, copy=False)
    broken_date = fields.Datetime(string='Fecha de rotura', readonly=True, copy=False)
    broken_reason = fields.Char(string='Motivo de la rotura', readonly=True, copy=False)
    notes = fields.Text(string='Notas')

    @api.depends('lot_ids')
    def _compute_lot_count(self):
        for pack in self:
            pack.lot_count = len(pack.lot_ids)

    @api.constrains('lot_ids', 'active', 'state')
    def _check_lots(self):
        for pack in self:
            if not pack.active or pack.state == 'sold':
                continue
            wrong = pack.lot_ids.filtered(lambda l: l.product_state_id.code != 'second_hand')
            if wrong:
                raise ValidationError(_(
                    "Un paquete de 2ª mano solo admite equipos en estado 2ª mano. No lo están: %s",
                    ', '.join(wrong.mapped('name'))))
            other = self.sudo().search([
                ('id', '!=', pack.id), ('state', '!=', 'sold'), ('lot_ids', 'in', pack.lot_ids.ids)])
            if other:
                shared = other.lot_ids & pack.lot_ids
                raise ValidationError(_(
                    "El equipo %(serial)s ya está en otro paquete activo (%(pack)s).",
                    serial=shared[0].name, pack=other[0].name))

    def _break(self, reason):
        """Solo responsable de inventario. Deja constancia."""
        if not self.env.su and not self.env.user.has_group('stock.group_stock_manager'):
            raise UserError(_("Solo un responsable de inventario puede romper un paquete."))
        for pack in self.sudo().filtered(lambda p: p.state == 'authorized'):
            pack.write({
                'state': 'broken', 'broken_by_id': self.env.uid,
                'broken_date': fields.Datetime.now(), 'broken_reason': reason or False,
            })
            pack.message_post(body=_(
                "Paquete roto por %(user)s. Motivo: %(reason)s",
                user=self.env.user.name, reason=reason or _("sin indicar")))

    def action_break(self):
        self._break(_("Roto a mano desde la ficha del paquete"))

    def action_authorize_again(self):
        if not self.env.user.has_group('stock.group_stock_manager'):
            raise UserError(_("Solo un responsable de inventario puede autorizar un paquete."))
        self.sudo().write({
            'state': 'authorized', 'broken_by_id': False, 'broken_date': False, 'broken_reason': False,
            'authorized_by_id': self.env.uid, 'authorized_date': fields.Date.context_today(self),
        })

    @api.model
    def _pack_of_lot(self, lot, company):
        """Paquete vigente (autorizado o roto) que contiene este equipo."""
        return self.sudo().search([
            ('lot_ids', 'in', lot.ids), ('state', 'in', ('authorized', 'broken')),
            ('company_id', '=', company.id)], limit=1)
