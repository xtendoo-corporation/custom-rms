# PROVISIONAL: copiar exactamente de producción (nombre, implied_ids, privilege_id, comment, menús) antes de usarlo en bases nuevas
COMERCIALES_GROUP_VALUES = {'name': 'Comerciales'}
COMERCIALES_IMPLIED_XMLIDS = ['base.group_user']


def pre_init_hook(env):
    if env.ref('custom.comerciales', raise_if_not_found=False):
        return

    values = dict(COMERCIALES_GROUP_VALUES)
    implied_ids = []
    for xmlid in COMERCIALES_IMPLIED_XMLIDS:
        implied_group = env.ref(xmlid, raise_if_not_found=False)
        if implied_group:
            implied_ids.append(implied_group.id)
    values['implied_ids'] = [(6, 0, implied_ids)]
    group = env['res.groups'].create(values)
    env['ir.model.data'].create({
        'module': 'custom',
        'name': 'comerciales',
        'model': 'res.groups',
        'res_id': group.id,
        'noupdate': True,
    })
