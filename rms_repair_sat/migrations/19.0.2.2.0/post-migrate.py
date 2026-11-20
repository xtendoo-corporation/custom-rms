import logging

from odoo import api, Command, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    admins = env.ref('base.group_system').all_user_ids
    for xmlid in ('repair_security.group_repair_user', 'repair_security.group_repair_manager'):
        group = env.ref(xmlid)
        users = group.user_ids - admins
        if users:
            group.write({'user_ids': [Command.unlink(user.id) for user in users]})
        _logger.info('SAT: retiradas %s asignaciones directas no administrativas de %s', len(users), xmlid)
    env['repair.order']._rms_initialize_panel()
