# -*- coding: utf-8 -*-
# El parámetro está en un bloque noupdate, que solo se carga al instalar:
# en bases que ya tenían el módulo hay que crearlo aquí. No se pisa si ya
# existe (alguien pudo configurarlo a mano antes de actualizar).
from odoo import SUPERUSER_ID, api

KEY = "rms_support_error_report.notify_email"


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    ICP = env["ir.config_parameter"]
    if not ICP.search_count([("key", "=", KEY)]):
        ICP.set_param(KEY, "notificaciones@rmsproaudio.com")
