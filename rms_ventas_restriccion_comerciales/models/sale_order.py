# -*- coding: utf-8 -*-

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError

from .restrictions import (
    hide_pricelists, is_comercial, lock_prices_and_taxes, only_own_customers, own_customers_domain,
    readable_suggested_recipients, restrict_partner_dropdown,
)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    rms_commercial_partner_id = fields.Many2one(
        comodel_name='res.partner',
        related='partner_id.commercial_partner_id',
        string='Empresa del cliente',
        store=True,
        index=True,
    )

    def _filter_restricted_values(self, vals):
        vals = dict(vals)
        if not self.env.su:
            if lock_prices_and_taxes(self.env):
                vals.pop('fiscal_position_id', None)
            # Con el permiso de listas de precios el comercial puede elegir la
            # tarifa aunque no pueda tocar precios ni descuentos a mano: los
            # descuentos de las líneas se recalculan a partir de ella.
            if hide_pricelists(self.env):
                vals.pop('pricelist_id', None)
        return vals

    def _assigned_opportunity_allows(self, lead, partner):
        """La oportunidad está asignada al usuario y su cliente es de la misma
        empresa que el del presupuesto."""
        lead = lead.sudo()
        return bool(lead) and lead.user_id == self.env.user and (
            lead.partner_id.commercial_partner_id == partner.commercial_partner_id
        )

    def _check_own_customer(self, vals):
        """Un comercial solo puede hacer presupuestos a sus propios clientes...
        Devuelve True si se permite solo por una oportunidad asignada."""
        if self.env.su or not vals.get('partner_id') or not only_own_customers(self.env):
            return False
        partner = self.env['res.partner'].sudo().browse(vals['partner_id'])
        if partner.filtered_domain(own_customers_domain(self.env)):
            return False
        # ...o al cliente de una oportunidad que le han asignado, desde ella
        # (INC-00007).
        Lead = self.env['crm.lead']
        if 'opportunity_id' in vals:
            leads = [Lead.browse(vals['opportunity_id'] or [])]
        elif self:
            leads = [order.opportunity_id for order in self]
        else:
            leads = [Lead.browse(self.env.context.get('default_opportunity_id') or [])]
        if all(self._assigned_opportunity_allows(lead, partner) for lead in leads):
            return True
        raise ValidationError(
            'Solo puedes hacer presupuestos a clientes que tengas asignados '
            'o desde una oportunidad suya que te hayan asignado '
            '(%s no es cliente tuyo).' % partner.display_name
        )

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [dict(vals) for vals in vals_list]
        default_partner_id = self.env.context.get('default_partner_id')
        for vals in vals_list:
            # El cliente puede venir por defecto en el contexto (p. ej. desde
            # la ficha del cliente) en vez de en los valores.
            checked = vals if 'partner_id' in vals else dict(vals, partner_id=default_partner_id)
            if self._check_own_customer(checked):
                # Odoo pondría de comercial al Vendedor del cliente, y un
                # comercial no puede crear presupuestos a nombre de otro: el
                # presupuesto de una oportunidad asignada queda a su nombre.
                vals['user_id'] = self.env.uid
        # Limpiar también los defaults que heredarían las líneas anidadas.
        context = self.env['sale.order.line']._filter_restricted_context()
        defaults = {key[8:]: value for key, value in context.items()
                    if key.startswith('default_')}
        allowed = self._filter_restricted_values(defaults)
        context = {key: value for key, value in context.items()
                   if not key.startswith('default_') or key[8:] in allowed}
        clean_self = self.with_context(context)
        return super(SaleOrder, clean_self).create(
            [self._filter_restricted_values(vals) for vals in vals_list]
        )

    def write(self, vals):
        self._check_own_customer(vals)
        return super().write(self._filter_restricted_values(vals))

    def unlink(self):
        # Los comerciales pueden borrar sus presupuestos (por si se equivocan al
        # crearlos), pero no los de otros. Odoo ya impide borrar los enviados o
        # confirmados: hay que cancelarlos antes.
        if not self.env.su and is_comercial(self.env) and any(
            order.user_id != self.env.user for order in self
        ):
            raise AccessError('Solo puedes eliminar tus propios presupuestos.')
        return super().unlink()

    def _message_get_suggested_recipients_batch(self, *args, **kwargs):
        # El cálculo lee el email de los seguidores y de los autores y
        # destinatarios del último mensaje, que pueden ser contactos que el
        # comercial no puede leer: sin sudo, el chatter falla con AccessError al
        # abrir el documento (INC-00007). Se calcula con sudo y se quitan de la
        # sugerencia los contactos que no puede leer.
        # También los Product Managers, que ven documentos de clientes cuya
        # ficha pueden dejar de leer al cerrarse la oportunidad.
        if self.env.su:
            return super()._message_get_suggested_recipients_batch(*args, **kwargs)
        # sudo: res.partner - seguidores y autores que el comercial no puede leer
        suggested = super(SaleOrder, self.sudo())._message_get_suggested_recipients_batch(*args, **kwargs)
        return readable_suggested_recipients(self.env, suggested)

    def _check_price_update_access(self, pricelist=False):
        # Actualizar precios solo aplica la tarifa elegida, así que basta con
        # el permiso de listas de precios.
        restricted = hide_pricelists if pricelist else lock_prices_and_taxes
        if not self.env.su and restricted(self.env):
            raise AccessError('No tienes permiso para modificar precios, descuentos o impuestos.')

    def action_update_taxes(self):
        self._check_price_update_access()
        return super().action_update_taxes()

    def action_update_prices(self):
        self._check_price_update_access(pricelist=True)
        return super().action_update_prices()

    def action_open_discount_wizard(self):
        self._check_price_update_access()
        return super().action_open_discount_wizard()

    @api.model
    def _get_view_cache_key(self, view_id=None, view_type='form', **options):
        # La vista procesada se cachea una sola vez para todos los usuarios, así
        # que la clave debe distinguir qué restricciones se aplican.
        key = super()._get_view_cache_key(view_id, view_type, **options)
        return key + (
            hide_pricelists(self.env), lock_prices_and_taxes(self.env), only_own_customers(self.env)
        )

    @api.model
    def _get_view(self, view_id=None, view_type='form', **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        if view_type == 'form' and only_own_customers(self.env):
            # En el desplegable de cliente solo aparecen sus propios clientes.
            restrict_partner_dropdown(self, arch)
        if hide_pricelists(self.env):
            # La lista de precios (tipo de cliente) se ve, pero es la del
            # cliente: Odoo la calcula al elegirlo y el comercial no la cambia.
            for node in arch.xpath("//field[@name='pricelist_id']"):
                node.set('readonly', '1')
            for node in arch.xpath("//button[@name='action_update_prices']"):
                node.set('invisible', '1')
        if lock_prices_and_taxes(self.env):
            # force_save: el valor que calcula Odoo al elegir producto o cliente
            # tiene que guardarse aunque el usuario no pueda editarlo.
            # discount1/2/3 son los del descuento triple (sale_triple_discount).
            for node in arch.xpath(
                "//field[@name='order_line']//field[@name='price_unit' or @name='tax_ids'"
                " or @name='discount' or @name='discount1' or @name='discount2' or @name='discount3']"
                " | //field[@name='fiscal_position_id']"
            ):
                node.set('readonly', '1')
                node.set('force_save', '1')
            # Los descuentos de la tarifa se ven aunque el comercial no tenga
            # el grupo «Descuentos en líneas» (que solo sirve para editarlos).
            for node in arch.xpath(
                "//field[@name='order_line']//field[@name='discount1' or @name='discount2' or @name='discount3']"
                " | //field[@name='order_line']//label[@for='discount1' or @for='discount2' or @for='discount3']"
                " | //field[@name='order_line']//div[@name='discount1' or @name='discount2' or @name='discount3']"
            ):
                node.attrib.pop('groups', None)
            # Recalcular impuestos tras cambiar la posición fiscal es otra forma
            # de cambiar el IVA de las líneas, y el asistente de descuento
            # aplica un descuento a todo el presupuesto.
            for node in arch.xpath(
                "//button[@name='action_update_taxes' or @name='action_open_discount_wizard']"
            ):
                node.set('invisible', '1')
        return arch, view
