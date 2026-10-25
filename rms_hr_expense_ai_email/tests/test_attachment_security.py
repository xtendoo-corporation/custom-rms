from unittest.mock import patch

from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged('post_install', '-at_install')
class TestAttachmentSecurity(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, login='f2_expense', groups='base.group_user')
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Empleado F2', 'user_id': cls.user.id,
            'company_id': cls.env.company.id,
        })
        cls.expense = cls.env['hr.expense'].create({
            'name': 'Ticket F2', 'employee_id': cls.employee.id,
        })
        cls.attachment = cls.env['ir.attachment'].create({
            'name': 'Ajeno', 'datas': 'dGVzdA==',
            'res_model': 'res.partner', 'res_id': cls.user.partner_id.id,
        })

    def test_foreign_attachment_write_and_create(self):
        with self.assertRaises(AccessError):
            self.expense.with_user(self.user).write({'ai_source_attachment_id': self.attachment.id})
        with self.assertRaises(AccessError):
            self.env['hr.expense'].with_user(self.user).create({
                'name': 'Inyección', 'employee_id': self.employee.id,
                'ai_source_attachment_id': self.attachment.id,
            })

    def test_cron_import_discards_foreign_attachment(self):
        # Simula un valor anterior al parche; se prueba el ejecutor del cron sin commits.
        self.expense.sudo().ai_source_attachment_id = self.attachment
        wizard = self.env['hr.expense.ai.wizard']
        with patch.object(type(wizard), 'create') as create:
            self.expense.sudo()._rms_run_ai_import(3)
            create.assert_not_called()
        self.assertFalse(self.expense.ai_source_attachment_id)
        self.assertEqual(self.expense.ai_import_attempts, 0)

    def test_own_attachment_allowed(self):
        self.attachment.write({'res_model': 'hr.expense', 'res_id': self.expense.id})
        self.expense.with_user(self.user).write({'ai_source_attachment_id': self.attachment.id})
        self.assertEqual(self.expense.ai_source_attachment_id, self.attachment)
