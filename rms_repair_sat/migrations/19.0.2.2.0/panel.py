"""Auxiliar para la migración; se llama desde post-migrate.py."""


def migrate_panel(env):
    env['repair.order']._rms_initialize_panel()
