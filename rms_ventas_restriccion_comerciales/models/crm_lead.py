# -*- coding: utf-8 -*-

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError

from .restrictions import (
    is_comercial, only_own_customers, own_customers_domain, readable_suggested_recipients,
    restrict_partner_dropdown,
)


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    # commercial_partner_id de crm no se guarda; este sí, para la regla de
    # acceso a los contactos de las oportunidades asignadas.
    rms_commercial_partner_id = fields.Many2one(
        comodel_name='res.partner',
        related='partner_id.commercial_partner_id',
        string='Empresa del cliente',
        store=True,
        index=True,
    )

    def _check_own_customer(self, partner_id):
        """Un comercial solo puede poner en sus oportunidades clientes suyos.
        Si el administrador le asigna una oportunidad de un cliente ajeno,
        puede trabajarla y cambiar a otro contacto de esa misma empresa, pero
        no a otra empresa ajena. Sin esto, asignarse una oportunidad le daría
        acceso a los contactos del cliente y a presupuestarle (INC-00007)."""
        if self.env.su or not partner_id or not only_own_customers(self.env):
            return
        partner = self.env['res.partner'].sudo().browse(partner_id)
        if partner.filtered_domain(own_customers_domain(self.env)):
            return
        if self and all(
            lead.partner_id and lead.partner_id.commercial_partner_id == partner.commercial_partner_id
            for lead in self.sudo()
        ):
            return
        raise ValidationError(
            'Solo puedes crear oportunidades a clientes que tengas asignados '
            '(%s no es cliente tuyo).' % partner.display_name
        )

    @api.model_create_multi
    def create(self, vals_list):
        default_partner_id = self.env.context.get('default_partner_id')
        for vals in vals_list:
            self._check_own_customer(vals['partner_id'] if 'partner_id' in vals else default_partner_id)
        return super().create(vals_list)

    def write(self, vals):
        if 'partner_id' in vals:
            self._check_own_customer(vals['partner_id'])
        return super().write(vals)

    def _prepare_customer_values(self, partner_name, is_company=False, parent_id=False):
        # El cliente que crea un comercial al convertir una iniciativa sin
        # vendedor es suyo; si no, no podría ponerlo en la oportunidad.
        values = super()._prepare_customer_values(partner_name, is_company=is_company, parent_id=parent_id)
        if not values.get('user_id') and not self.env.su and only_own_customers(self.env):
            values['user_id'] = self.env.uid
        return values

    def unlink(self):
        # Los comerciales pueden borrar sus oportunidades, pero no las de otros.
        if not self.env.su and is_comercial(self.env) and any(
            lead.user_id != self.env.user for lead in self
        ):
            raise AccessError('Solo puedes eliminar tus propias oportunidades.')
        return super().unlink()

    def _message_get_suggested_recipients_batch(self, *args, **kwargs):
        # El cálculo lee el email de los seguidores y de los autores y
        # destinatarios del último mensaje, que pueden ser contactos que el
        # comercial no puede leer: sin sudo, el chatter falla con AccessError al
        # abrir el documento (INC-00007). Se calcula con sudo y se quitan de la
        # sugerencia los contactos que no puede leer.
        if self.env.su or not is_comercial(self.env):
            return super()._message_get_suggested_recipients_batch(*args, **kwargs)
        # sudo: res.partner - seguidores y autores que el comercial no puede leer
        suggested = super(CrmLead, self.sudo())._message_get_suggested_recipients_batch(*args, **kwargs)
        return readable_suggested_recipients(self.env, suggested)

    @api.model
    def _get_view_cache_key(self, view_id=None, view_type='form', **options):
        # La vista procesada se cachea una sola vez para todos los usuarios.
        key = super()._get_view_cache_key(view_id, view_type, **options)
        return key + (only_own_customers(self.env),)

    @api.model
    def _get_view(self, view_id=None, view_type='form', **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        if view_type == 'form' and only_own_customers(self.env):
            # Formulario y alta rápida del kanban: solo sus propios clientes.
            restrict_partner_dropdown(self, arch)
        return arch, view
