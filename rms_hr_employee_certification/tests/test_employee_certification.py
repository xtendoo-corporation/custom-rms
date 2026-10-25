from dateutil.relativedelta import relativedelta
from psycopg2 import IntegrityError

from odoo import Command, fields
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestEmployeeCertification(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env['res.company'].create({'name': 'Certificaciones A'})
        cls.company_b = cls.env['res.company'].create({'name': 'Certificaciones B'})
        cls.hr_user = cls.env['res.users'].create({
            'name': 'Responsable certificaciones A',
            'login': 'test_certificaciones_a',
            'company_id': cls.company_a.id,
            'company_ids': [Command.set([cls.company_a.id])],
            'group_ids': [Command.set([cls.env.ref('hr.group_hr_user').id])],
        })
        cls.category = cls.env['rms.hr.certification.category'].create({
            'name': 'Categoría prueba renovación',
        })
        cls.certification_type = cls.env['rms.hr.certification.type'].create({
            'name': 'Certificación prueba renovación',
            'code': 'TEST_RENEWAL',
            'category_id': cls.category.id,
            'validity_months': 12,
            'reminder_days': 30,
            'responsible_id': cls.hr_user.id,
        })
        cls.employee_a = cls.env['hr.employee'].create({
            'name': 'Empleado A', 'company_id': cls.company_a.id,
        })
        cls.employee_b = cls.env['hr.employee'].create({
            'name': 'Empleado B', 'company_id': cls.company_b.id,
        })

    def _create_certification(self, employee):
        return self.env['rms.hr.employee.certification'].create({
            'employee_id': employee.id,
            'certification_type_id': self.certification_type.id,
            'date_obtained': fields.Date.today() - relativedelta(months=12),
        })

    def test_hr_company_isolation(self):
        own = self._create_certification(self.employee_a)
        other = self._create_certification(self.employee_b)
        for group in ('hr.group_hr_user',
                      'rms_hr_employee_certification.group_hr_certification_manager'):
            with self.subTest(group=group):
                self.hr_user.group_ids = [Command.set([
                    self.env.ref('base.group_user').id, self.env.ref(group).id,
                ])]
                certifications = self.env['rms.hr.employee.certification'].with_user(
                    self.hr_user).with_context(allowed_company_ids=[self.company_a.id])
                self.assertEqual(certifications.search([
                    ('id', 'in', (own | other).ids),
                ]), certifications.browse(own.id))
                with self.assertRaises(AccessError):
                    certifications.browse(other.id).read(['date_obtained'])

    def test_duplicate_category_name(self):
        with self.assertRaises(IntegrityError), self.cr.savepoint():
            # La restricción debe rechazar el duplicado en la base de datos.
            self.category.copy({'name': self.category.name})
            self.env.flush_all()

    def test_duplicate_type_code(self):
        with self.assertRaises(IntegrityError), self.cr.savepoint():
            self.certification_type.copy({'code': self.certification_type.code})
            self.env.flush_all()

    def test_cron_notifies_once_per_expiration(self):
        cert = self._create_certification(self.employee_a)
        generic = cert.activity_schedule(
            'mail.mail_activity_data_todo', user_id=self.hr_user.id,
            summary='Otra tarea pendiente',
        )
        activity_type = self.env.ref(
            'rms_hr_employee_certification.mail_activity_type_certification_renewal')

        def renewal_activities():
            return cert.activity_ids.filtered(
                lambda activity: activity.activity_type_id == activity_type)

        cert._cron_check_certification_renewals()
        self.assertEqual(len(renewal_activities()), 1)
        self.assertEqual(cert.renewal_notified_date, cert.date_expiration)
        cert._cron_check_certification_renewals()
        self.assertEqual(len(renewal_activities()), 1)
        renewal_activities().action_feedback(feedback='Revisado, pendiente de renovar')
        cert._cron_check_certification_renewals()
        self.assertFalse(renewal_activities())
        self.assertTrue(generic.exists())
        # Una nueva caducidad debe permitir un nuevo aviso aunque el anterior esté hecho.
        cert.date_obtained += relativedelta(days=1)
        cert._cron_check_certification_renewals()
        self.assertEqual(len(renewal_activities()), 1)
        self.assertEqual(cert.renewal_notified_date, cert.date_expiration)
