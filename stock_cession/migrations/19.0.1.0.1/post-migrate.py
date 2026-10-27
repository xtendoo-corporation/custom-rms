from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    # El valor por defecto del nuevo campo no refleja la compañía histórica.
    cr.execute('''
        UPDATE stock_cession AS cession
           SET company_id = COALESCE(location.company_id, %s)
          FROM stock_location AS location
         WHERE location.id = cession.location_src_id
    ''', (env.ref('base.main_company').id,))
    env['stock.cession'].invalidate_model(['company_id'])
