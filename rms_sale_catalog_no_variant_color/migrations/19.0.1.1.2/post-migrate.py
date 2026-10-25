from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    # Aplicar una sola vez la misma regla de color que usan los valores nuevos.
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['product.attribute.value'].search([])._compute_color()
    env['product.template.attribute.value'].search([])._compute_color()
    env.flush_all()
