"""Guardar grupos antes de que los datos de la actualización los sustituyan."""
import json
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    params = env['ir.config_parameter'].sudo()
    for xmlid in ('repair.menu_repair_order', 'repair.action_report_repair_order'):
        key = 'rms_repair_sat.original_groups.' + xmlid
        record = env.ref(xmlid, raise_if_not_found=False)
        if record and params.get_param(key, default=None) is None:
            params.set_param(key, json.dumps(record.group_ids.ids))
