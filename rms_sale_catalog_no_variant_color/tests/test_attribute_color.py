from pathlib import Path
from runpy import run_path

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAttributeColor(TransactionCase):
    def test_init_preserves_manual_color(self):
        attribute = self.env['product.attribute'].create({'name': 'Estado W2H'})
        value = self.env['product.attribute.value'].create({
            'attribute_id': attribute.id, 'name': 'Nuevo W2H',
        })
        value.color = 7
        self.env.flush_all()
        value.init()
        self.env.invalidate_all()
        self.assertEqual(value.color, 7)

    def test_migration_uses_compute_rule(self):
        attribute = self.env['product.attribute'].create({'name': 'Estado migración W2H'})
        values = self.env['product.attribute.value'].create([
            {'attribute_id': attribute.id, 'name': name, 'color': 7}
            for name in ('NUEVO demo W2H', '2 MANO demo W2H', 'DEMO W2H', 'Otro W2H')
        ])
        migration = Path(__file__).resolve().parents[1] / 'migrations/19.0.1.1.2/post-migrate.py'
        run_path(str(migration))['migrate'](self.env.cr, '1.1')
        self.env.invalidate_all()
        self.assertEqual(values.mapped('color'), [10, 3, 2, 0])
