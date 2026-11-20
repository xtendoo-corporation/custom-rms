from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    cr.execute("UPDATE repair_order SET rms_stage = 'repair' WHERE rms_stage = 'accepted'")
    cr.execute("UPDATE repair_order SET rms_entry_way = 'courier' WHERE rms_entry_way = 'shipping'")
    cr.execute("UPDATE repair_order SET rms_owner_type = 'customer' WHERE rms_owner_type IS NULL")
    for warehouse in env['stock.warehouse'].search([]):
        if not warehouse._rms_sat_site():
            continue
        if warehouse.rms_sat_location_id and warehouse.rms_sat_location_id.location_id != warehouse.view_location_id:
            warehouse.rms_sat_location_id.location_id = warehouse.view_location_id
        if not warehouse.rms_ra_location_id:
            label = 'RA Madrid' if warehouse._rms_sat_site()[0] == 'madrid' else 'RA Sevilla'
            warehouse.rms_ra_location_id = env['stock.location'].search([('name', '=', label), ('location_id', 'child_of', warehouse.view_location_id.id), ('company_id', '=', warehouse.company_id.id)], limit=1)
        if warehouse.rms_ra_location_id and warehouse.rms_ra_location_id.location_id != warehouse.view_location_id:
            warehouse.rms_ra_location_id.location_id = warehouse.view_location_id
        if warehouse.rms_sat_factory_location_id and warehouse.rms_sat_factory_location_id.location_id != warehouse.rms_sat_location_id:
            warehouse.rms_sat_factory_location_id.location_id = warehouse.rms_sat_location_id
    env['stock.warehouse']._rms_setup_sat()
    env['repair.order'].search([('lot_id', '!=', False)])._compute_rms_warranty()
