"""Conserva los grupos personalizados antes de ocultar los accesos estándar."""
import json

_TARGETS = ('repair.menu_repair_order', 'repair.action_report_repair_order')
_PREFIX = 'rms_repair_sat.original_groups.'


def pre_init_hook(env):
    params = env['ir.config_parameter'].sudo()
    for xmlid in _TARGETS:
        record = env.ref(xmlid, raise_if_not_found=False)
        if record and params.get_param(_PREFIX + xmlid, default=None) is None:
            params.set_param(_PREFIX + xmlid, json.dumps(record.group_ids.ids))


def uninstall_hook(env):
    params = env['ir.config_parameter'].sudo()
    for xmlid in _TARGETS:
        key = _PREFIX + xmlid
        saved = params.get_param(key, default=None)
        record = env.ref(xmlid, raise_if_not_found=False)
        if saved is not None and record:
            group_ids = env['res.groups'].browse(json.loads(saved)).exists().ids
            record.write({'group_ids': [(6, 0, group_ids)]})
        params.search([('key', '=', key)]).unlink()
