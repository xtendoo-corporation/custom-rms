# -*- coding: utf-8 -*-

GROUP_COMERCIALES = 'custom.comerciales'
GROUP_PRICELIST = 'rms_ventas_restriccion_comerciales.group_comerciales_pricelist'
GROUP_QUOTATION_FULL_EDIT = 'rms_ventas_restriccion_comerciales.group_comerciales_quotation_full_edit'
GROUP_ALL_CUSTOMERS = 'rms_ventas_restriccion_comerciales.group_comerciales_all_customers'


def _is_restricted(env, allowed_group):
    user = env.user
    return bool(env.ref(GROUP_COMERCIALES, raise_if_not_found=False)) and (
        user.has_group(GROUP_COMERCIALES) and not user.has_group(allowed_group)
    )


def is_comercial(env):
    """El usuario pertenece al grupo Comerciales."""
    return bool(env.ref(GROUP_COMERCIALES, raise_if_not_found=False)) and env.user.has_group(GROUP_COMERCIALES)


def only_own_customers(env):
    """El usuario es comercial y solo puede hacer presupuestos a sus clientes."""
    return _is_restricted(env, GROUP_ALL_CUSTOMERS)


def own_customer_user_ids(env):
    """El usuario y los comerciales cuyos clientes lleva también."""
    user = env.user
    return [user.id] + user.sudo().rms_shared_customer_user_ids.ids


def own_customers_domain(env):
    """Clientes cuyo comercial asignado (Vendedor) es el usuario o uno de los
    comerciales cuyos clientes lleva también, directamente o a través de su
    empresa."""
    user_ids = own_customer_user_ids(env)
    return ['|', ('user_id', 'in', user_ids), ('commercial_partner_id.user_id', 'in', user_ids)]


def hide_pricelists(env):
    """El usuario es comercial y no tiene permiso para ver listas de precios."""
    return _is_restricted(env, GROUP_PRICELIST)


def lock_prices_and_taxes(env):
    """El usuario es comercial y no puede cambiar precios, descuentos ni impuestos."""
    return _is_restricted(env, GROUP_QUOTATION_FULL_EDIT)


def readable_suggested_recipients(env, suggested):
    """Quita de los destinatarios sugeridos del chatter los contactos que el
    usuario no puede leer (calculados con sudo)."""
    partner_ids = {
        recipient['partner_id']
        for recipients in suggested.values() for recipient in recipients
        if recipient.get('partner_id')
    }
    readable = set(env['res.partner'].browse(partner_ids)._filtered_access('read').ids)
    return {
        res_id: [r for r in recipients if not r.get('partner_id') or r['partner_id'] in readable]
        for res_id, recipients in suggested.items()
    }
