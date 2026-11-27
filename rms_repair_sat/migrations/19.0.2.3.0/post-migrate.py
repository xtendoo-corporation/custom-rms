from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    params = env['ir.config_parameter'].sudo()
    if params.get_param('rms_repair_sat.default_return_shipping') == 'collect':
        params.set_param('rms_repair_sat.default_return_shipping', 'invoice')
    params.search([('key', '=', 'rms_repair_sat.used_price_factor')]).unlink()
    hour = env.ref('rms_repair_sat.product_labour_hour', raise_if_not_found=False)
    if hour and not hour.list_price:
        hour.list_price = 50
    shipping = env.ref('rms_repair_sat.product_sat_shipping', raise_if_not_found=False)
    if shipping:
        repairs = env['repair.order'].search([('rms_stage', 'not in', ('delivered', 'cancel')),
                                              ('rms_return_shipping', '=', 'collect')])
        repairs.filtered(lambda r: not r.sale_order_id.order_line.filtered(
            lambda line: line.product_id == shipping)).write({'rms_return_shipping': 'invoice'})
