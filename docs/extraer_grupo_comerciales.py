# Solo lectura. Ejecutar en producción con:
#   odoo shell -d <base> --no-http < docs/extraer_grupo_comerciales.py
# Imprime la definición del grupo custom.comerciales para copiarla en
# rms_ventas_restriccion_comerciales/hooks.py. No escribe nada.

def xmlid(record):
    return ', '.join(record.get_external_id().values()) or '(sin xmlid) id=%s' % record.id


group = env.ref('custom.comerciales', raise_if_not_found=False)
data = env['ir.model.data'].search([('module', '=', 'custom'), ('name', '=', 'comerciales')])
print('ir.model.data:', data.read(['module', 'name', 'model', 'res_id', 'noupdate']))
print('módulo custom instalado:', bool(env['ir.module.module'].search_count(
    [('name', '=', 'custom'), ('state', '=', 'installed')])))
if group:
    print('name:', group.name)
    print('comment:', group.comment)
    print('privilege_id:', group.privilege_id and xmlid(group.privilege_id))
    print('implied_ids:', [xmlid(g) for g in group.implied_ids])
    print('grupos que lo implican:', [xmlid(g) for g in env['res.groups'].search([('implied_ids', 'in', group.id)])])
    print('menús:', [xmlid(m) for m in group.menu_access])
    print('vistas:', [xmlid(v) for v in group.view_access])
    print('ACL:', [(a.name, a.model_id.model, a.perm_read, a.perm_write, a.perm_create, a.perm_unlink)
                   for a in group.model_access])
    print('reglas:', [(xmlid(r), r.model_id.model, r.domain_force) for r in group.rule_groups])
    print('usuarios:', len(group.user_ids))
