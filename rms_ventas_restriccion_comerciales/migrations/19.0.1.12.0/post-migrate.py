# -*- coding: utf-8 -*-

from odoo import SUPERUSER_ID, api

from odoo.addons.rms_ventas_restriccion_comerciales.pm_access import drop_pm_see_all, mark_pm_closing_stages


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    mark_pm_closing_stages(env)
    drop_pm_see_all(env)
