# -*- coding: utf-8 -*-

GROUP_COMERCIALES = 'custom.comerciales'
GROUP_PRICELIST = 'rms_ventas_restriccion_comerciales.group_comerciales_pricelist'
GROUP_QUOTATION_FULL_EDIT = 'rms_ventas_restriccion_comerciales.group_comerciales_quotation_full_edit'


def _is_restricted(env, allowed_group):
    user = env.user
    return user.has_group(GROUP_COMERCIALES) and not user.has_group(allowed_group)


def hide_pricelists(env):
    """El usuario es comercial y no tiene permiso para ver listas de precios."""
    return _is_restricted(env, GROUP_PRICELIST)


def lock_prices_and_taxes(env):
    """El usuario es comercial y no puede cambiar precios, descuentos ni impuestos."""
    return _is_restricted(env, GROUP_QUOTATION_FULL_EDIT)
