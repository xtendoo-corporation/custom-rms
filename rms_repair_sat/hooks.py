# -*- coding: utf-8 -*-


def post_init_hook(env):
    """repair_security (OCA 19.0) quiere dar "Reparaciones: Administrador" a
    quien ya tenía Inventario, pero en Odoo 19 usa group.user_ids (solo los
    usuarios puestos a mano en el grupo) con (6, 0, ...): deja fuera a quien
    tiene Inventario por un grupo superior (p. ej. el administrador) e incluso
    se los quita. Aquí se completa lo que pretendía, sin quitar a nadie."""
    stock_users = env.ref('stock.group_stock_user').all_user_ids.filtered(lambda u: not u.share)
    manager = env.ref('repair_security.group_repair_manager')
    missing = stock_users - manager.all_user_ids
    if missing:
        manager.write({'user_ids': [(4, user.id) for user in missing]})
