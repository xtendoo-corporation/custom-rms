from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestSatSecurityV3(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.commercial = new_test_user(cls.env, login='sat_comercial_v3',
                                       groups='base.group_user,custom.comerciales')
        cls.other = new_test_user(cls.env, login='sat_otro_comercial_v3',
                                  groups='base.group_user,custom.comerciales')
        cls.warehouse_user = new_test_user(cls.env, login='sat_almacen_v3',
                                           groups='stock.group_stock_user,rms_repair_sat.group_sat_warehouse')
        cls.customer = cls.env['res.partner'].create({'name': 'Cliente propio SAT', 'user_id': cls.commercial.id})
        cls.other_customer = cls.env['res.partner'].create({'name': 'Cliente ajeno SAT', 'user_id': cls.other.id})
        product = cls.env['product.product'].create({'name': 'Equipo SAT seguridad'})
        cls.own_repair = cls.env['repair.order'].create({'partner_id': cls.customer.id, 'product_id': product.id})
        cls.other_repair = cls.env['repair.order'].create({'partner_id': cls.other_customer.id, 'product_id': product.id})

    def test_commercial_reads_only_own_customer_without_write(self):
        self.env['ir.rule'].create({'name': 'Contactos del responsable en prueba',
            'model_id': self.env['ir.model']._get_id('res.partner'),
            'domain_force': "['|', ('user_id', '=', user.id), ('user_id', '=', False)]"})
        repairs = self.env['repair.order'].with_user(self.commercial).search([
            ('id', 'in', (self.own_repair.id, self.other_repair.id))])
        self.assertEqual(repairs.ids, self.own_repair.ids)
        with self.assertRaises(AccessError):
            self.own_repair.with_user(self.commercial).write({'rms_fault': 'Cambio'})

    def test_warehouse_cannot_diagnose_or_validate_disassembly(self):
        with self.assertRaises(AccessError):
            self.own_repair.with_user(self.warehouse_user).action_rms_wait_part()
        with self.assertRaises(AccessError):
            self.own_repair.with_user(self.warehouse_user).action_repair_start()
        disassembly = self.env['rms.disassembly'].with_user(self.warehouse_user).new({})
        with self.assertRaises(AccessError):
            disassembly.action_done()

    def test_admin_implies_manager_and_technician(self):
        admin = self.env.ref('base.user_admin')
        self.assertTrue(admin.has_group('rms_repair_sat.group_sat_manager'))
        self.assertTrue(admin.has_group('rms_repair_sat.group_sat_technician'))
        self.assertTrue(admin.has_group('rms_repair_sat.group_sat_warehouse'))
