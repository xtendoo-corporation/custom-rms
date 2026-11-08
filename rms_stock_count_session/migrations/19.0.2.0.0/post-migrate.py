"""Preserve legacy Sage evidence and reconciliation links, without rebuilding."""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    migrate_expected(env)


def migrate_expected(env):
    Expected = env['rms.stock.count.expected']
    Snapshot = env['rms.sage.snapshot']
    Stock = env['rms.sage.stock.line']
    Warehouse = env['rms.sage.warehouse']
    missing_brand = False
    for session in env['rms.stock.count.session'].search([]):
        legacy = Expected.search([('session_id', '=', session.id)])
        if not legacy:
            continue
        marker = 'Migrado de %s [%s]' % (session.name, session.id)
        if Snapshot.search_count([('name', '=like', marker + '%'), ('company_id', '=', session.company_id.id)]):
            continue
        grouped = {}
        for line in legacy:
            category = line.product_id.categ_id
            while category.parent_id:
                category = category.parent_id
            if not category:
                if not missing_brand:
                    missing_brand = env['product.category'].search([('name', '=', 'Sin marca'), ('parent_id', '=', False)], limit=1)
                    missing_brand = missing_brand or env['product.category'].create({'name': 'Sin marca'})
                category = missing_brand
            grouped.setdefault(category.id, []).append(line)
        brand_ids, warehouse_ids = [], []
        for brand_id, lines in grouped.items():
            snapshot = Snapshot.create({'name': marker + ' · ' + env['product.category'].browse(brand_id).name,
                                        'sage_company_code': '01', 'company_id': session.company_id.id,
                                        'brand_categ_id': brand_id, 'export_date': (session.date_start or session.create_date).date(),
                                        'state': 'current'})
            brand_ids.append(brand_id)
            for old in lines:
                warehouse = Warehouse.search([('sage_company_code', '=', '01'), ('code', '=', old.warehouse_code)], limit=1)
                warehouse = warehouse or Warehouse.create({'name': old.warehouse_code, 'code': old.warehouse_code,
                                                            'company_id': session.company_id.id, 'sage_company_code': '01'})
                warehouse_ids.append(warehouse.id)
                state = {'Demo': 'demo', '2Mano': '2mano'}.get(old.state_hint, 'nuevo')
                new = Stock.create({'snapshot_id': snapshot.id, 'is_current': True,
                                    'warehouse_code': old.warehouse_code, 'sage_warehouse_id': warehouse.id,
                                    'article_code': old.article_code, 'model_code': old.model_code,
                                    'state': state, 'serial': old.serial, 'quantity': old.quantity,
                                    'cost': old.cost, 'product_id': old.product_id.id,
                                    'match_state': 'ok' if old.product_id else 'sin_producto'})
                env['rms.stock.count.sage.line'].search([('expected_id', '=', old.id)]).write({'stock_line_id': new.id})
        session.write({'sage_company_code': '01', 'brand_categ_ids': [(6, 0, brand_ids)],
                       'sage_warehouse_ids': [(6, 0, list(set(warehouse_ids)))]})
    Stock._update_duplicates()
