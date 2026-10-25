from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..hooks import pre_init_hook


@tagged('post_install', '-at_install')
class TestComercialesGroup(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        group = cls.env.ref('custom.comerciales', raise_if_not_found=False)
        # Conservar la comprobación de instalación antes de preparar el grupo.
        cls.group_existed_after_install = bool(group)
        if not group:
            group = cls.env['res.groups'].create({'name': 'Comerciales'})
            cls.env['ir.model.data'].create({
                'module': 'custom', 'name': 'comerciales',
                'model': 'res.groups', 'res_id': group.id,
                'noupdate': True,
            })
        cls.group = group

    def test_xmlid_exists_after_install(self):
        self.assertTrue(self.group_existed_after_install)
        self.assertEqual(self.env.ref('custom.comerciales'), self.group)

    def test_new_group_matches_production_definition(self):
        # Simula una base sin el grupo (se deshace al acabar el test) para
        # comprobar la creación sin depender del grupo ya existente.
        self.group.name = 'COMERCIALES (anterior)'  # el nombre es único por privilegio
        self.env['ir.model.data'].search([('module', '=', 'custom'), ('name', '=', 'comerciales')]).unlink()
        self.env.registry.clear_cache()
        pre_init_hook(self.env)
        group = self.env.ref('custom.comerciales')
        self.assertNotEqual(group, self.group)
        self.assertEqual(group.with_context(lang='en_US').name, 'COMERCIALES')
        self.assertEqual(group.privilege_id, self.env.ref('sales_team.res_groups_privilege_sales'))
        self.assertEqual(group.implied_ids, self.env.ref('sales_team.group_sale_salesman'))
        self.assertFalse(group.share)

    def test_existing_group_is_untouched(self):
        users_field = 'user_ids' if 'user_ids' in self.group._fields else 'users'
        fields = ['name', 'implied_ids', users_field, 'write_date']
        self.env.flush_all()
        before = self.group.read(fields)
        group_count = self.env['res.groups'].search_count([])
        xmlid_count = self.env['ir.model.data'].search_count([])

        pre_init_hook(self.env)

        self.env.flush_all()
        self.group.invalidate_recordset(fields)
        self.assertEqual(self.group.read(fields), before)
        self.assertEqual(self.env['res.groups'].search_count([]), group_count)
        self.assertEqual(self.env['ir.model.data'].search_count([]), xmlid_count)
