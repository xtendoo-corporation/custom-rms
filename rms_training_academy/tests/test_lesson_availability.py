from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged('post_install', '-at_install')
class TestLessonAvailability(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, login='w2f_academy', groups='base.group_user')
        cls.path = cls.env['rms.training.path'].create({'name': 'Ruta W2F'})
        cls.available = cls.env['rms.training.lesson'].create({'name': 'Disponible', 'path_id': cls.path.id})
        cls.unavailable = cls.env['rms.training.lesson'].create({
            'name': 'Restringida', 'path_id': cls.path.id, 'group_xmlids': 'base.group_system',
        })

    def test_unavailable_cannot_create_progress(self):
        lessons = (self.available | self.unavailable).with_user(self.user)
        with self.assertRaises(AccessError):
            lessons.action_mark_done()
        self.assertFalse(self.env['rms.training.progress'].search([
            ('lesson_id', 'in', lessons.ids), ('user_id', '=', self.user.id),
        ]))

    def test_unavailable_cannot_update_progress(self):
        progress = self.env['rms.training.progress'].create({
            'lesson_id': self.unavailable.id, 'user_id': self.user.id, 'state': 'in_progress',
        })
        with self.assertRaises(AccessError):
            self.unavailable.with_user(self.user).action_mark_done()
        self.assertEqual(progress.state, 'in_progress')
        self.assertFalse(progress.date_done)

    def test_available_can_be_completed(self):
        self.available.with_user(self.user).action_mark_done()
        self.assertEqual(self.available.with_user(self.user).my_state, 'done')
