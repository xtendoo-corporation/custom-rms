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


def only_own_customers(env):
    """El usuario es comercial y solo puede hacer presupuestos a sus clientes."""
    return _is_restricted(env, GROUP_ALL_CUSTOMERS)


def own_customers_domain(uid):
    """Clientes cuyo comercial asignado (Vendedor) es el usuario, directamente
    o a través de su empresa."""
    return ['|', ('user_id', '=', uid), ('commercial_partner_id.user_id', '=', uid)]


def hide_pricelists(env):
    """El usuario es comercial y no tiene permiso para ver listas de precios."""
    return _is_restricted(env, GROUP_PRICELIST)


def lock_prices_and_taxes(env):
    """El usuario es comercial y no puede cambiar precios, descuentos ni impuestos."""
    return _is_restricted(env, GROUP_QUOTATION_FULL_EDIT)
