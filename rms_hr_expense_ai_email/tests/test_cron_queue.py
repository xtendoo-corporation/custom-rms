from unittest.mock import patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestExpenseCronQueue(TransactionCase):
    def test_email_without_attachment_finishes_once(self):
        employee = self.env['hr.employee'].create({'name': 'Empleado cola W2G'})
        expense = self.env['hr.expense'].create({
            'name': 'Correo sin documento', 'employee_id': employee.id,
            'created_from_email_alias': True,
        })
        # El cron confirma trabajo; en TransactionCase se evita confirmar la prueba.
        with patch.object(type(self.env.cr), 'commit'), \
                patch.object(type(expense), '_rms_run_ai_import') as run:
            expense._cron_process_pending_ai_email_expenses()
            self.assertTrue(expense.ai_processed)
            self.assertEqual(expense.ai_import_attempts, 0)
            messages = len(expense.message_ids)
            expense._cron_process_pending_ai_email_expenses()
            self.assertEqual(len(expense.message_ids), messages)
            run.assert_not_called()
