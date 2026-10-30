# Solo lectura. Ejecutar en producción con:
#   odoo shell -d <base> --no-http < docs/diagnosticar_menu_gastos.py
# Explica por qué el menú Gastos (hr_expense.menu_hr_expense_root) no le
# aparece a algunos usuarios internos. No escribe nada.
#
# En Odoo 19 estándar el menú raíz no tiene grupos y "Mis gastos" solo pide
# base.group_user, así que cualquier usuario interno debería verlo. Si no lo
# ve, es que en la base se ha cambiado algo: grupos de los menús o de las
# acciones, un menú o acción archivados, o el usuario no es interno.

def xmlid(record):
    return ', '.join(record.get_external_id().values()) or '(sin xmlid) id=%s' % record.id


Menu = env['ir.ui.menu'].sudo().with_context(active_test=False)
root = env.ref('hr_expense.menu_hr_expense_root', raise_if_not_found=False)
if not root:
    print('hr_expense no está instalado o se ha borrado el menú raíz')
else:
    print('== Menús de Gastos (en estándar: raíz sin grupos, Mis gastos e Informes con base.group_user)')
    for menu in Menu.search([('id', 'child_of', root.id)], order='parent_path'):
        action = menu.action
        print('%s | activo=%s | grupos=%s | acción=%s | grupos_acción=%s' % (
            menu.complete_name, menu.active,
            [xmlid(g) for g in menu.group_ids],
            action and ('%s,%s existe=%s' % (action._name, action.id, bool(action.exists()))),
            action and action.exists() and 'group_ids' in action and [xmlid(g) for g in action.sudo().group_ids],
        ))

    print('\n== Usuarios internos que NO ven Gastos')
    users = env['res.users'].search([('share', '=', False)])
    for user in users:
        visible = env['ir.ui.menu'].with_user(user)._visible_menu_ids()
        if root.id in visible:
            continue
        print('- %s (%s) grupos: %s' % (user.name, user.login, sorted(xmlid(g) for g in user.group_ids)))
        print('    leer hr.expense: %s' % env['ir.model.access'].with_user(user).check('hr.expense', 'read', False))

    print('\n(Los usuarios portal/públicos nunca ven Gastos: si a alguien le falta,')
    print(' comprobar primero que en su ficha el Tipo de usuario sea "Usuario interno".)')
