"""Guardar los grupos anteriores antes de cargar los nuevos datos XML."""
import json
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    params = env['ir.config_parameter'].sudo()
    for xmlid in ('stock.action_report_lot_label', 'stock.label_lot_template'):
        key = 'rms_stock_lot_label_print.original_groups.' + xmlid
        record = env.ref(xmlid, raise_if_not_found=False)
        if record and params.get_param(key, default=None) is None:
            params.set_param(key, json.dumps(record.group_ids.ids))
