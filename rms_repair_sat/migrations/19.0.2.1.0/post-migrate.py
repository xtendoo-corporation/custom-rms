from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    sequence = env.ref('rms_repair_sat.seq_rms_disassembly', raise_if_not_found=False)
    if sequence:
        sequence.prefix = 'DSP/%(year)s/'
    env['stock.warehouse']._rms_setup_sat()
