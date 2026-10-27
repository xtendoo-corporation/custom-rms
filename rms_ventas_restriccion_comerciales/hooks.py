# Definición del grupo custom.comerciales tal y como se creó a mano en
# producción (leída de la base rms el 25/10/2026). Solo se usa para crearlo
# en bases nuevas: si el grupo ya existe, el hook no toca nada.
COMERCIALES_GROUP_NAME = {'en_US': 'COMERCIALES', 'es_ES': 'COMERCIALES'}
COMERCIALES_PRIVILEGE_XMLID = 'sales_team.res_groups_privilege_sales'
COMERCIALES_IMPLIED_XMLIDS = ['sales_team.group_sale_salesman']
# Menús asignados a mano en producción. Son de otros módulos: solo se
# enlazan los que ya estén instalados al crear el grupo.
COMERCIALES_MENU_XMLIDS = [
    'crm.crm_menu_root',
    'rms_comerciales_tasks_shortcut.menu_comerciales_my_tasks',
    'rms_global_equipment_map.menu_global_equipment_map',
]


def _refs(env, xmlids):
    return [record.id for record in (env.ref(xmlid, raise_if_not_found=False) for xmlid in xmlids) if record]


def pre_init_hook(env):
    if env.ref('custom.comerciales', raise_if_not_found=False):
        return

    privilege = env.ref(COMERCIALES_PRIVILEGE_XMLID, raise_if_not_found=False)
    group = env['res.groups'].create({
        'name': COMERCIALES_GROUP_NAME['en_US'],
        'privilege_id': privilege.id if privilege else False,
        'implied_ids': [(6, 0, _refs(env, COMERCIALES_IMPLIED_XMLIDS))],
        'menu_access': [(6, 0, _refs(env, COMERCIALES_MENU_XMLIDS))],
    })
    for lang, name in COMERCIALES_GROUP_NAME.items():
        if env['res.lang']._lang_get(lang):
            group.with_context(lang=lang).name = name
    env['ir.model.data'].create({
        'module': 'custom',
        'name': 'comerciales',
        'model': 'res.groups',
        'res_id': group.id,
        'noupdate': False,
    })
