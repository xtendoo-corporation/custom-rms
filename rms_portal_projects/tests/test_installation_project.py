import base64
from unittest.mock import patch

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase

from ..models import installation_project


class TestInstallationProject(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({'name': 'Cliente proyecto'})
        cls.other_partner = cls.env['res.partner'].create({'name': 'Otro cliente'})

    def _project(self, **values):
        vals = {
            'name': 'Proyecto de prueba',
            'partner_id': self.partner.id,
            'file_name': 'proyecto.html',
            'file_data': base64.b64encode(b'<html>Proyecto</html>'),
        }
        vals.update(values)
        return self.env['rms.installation.project'].create(vals)

    def test_invalid_extension(self):
        for filename in ('proyecto.pdf', 'proyecto.html.exe', False):
            with self.subTest(filename=filename):
                with self.assertRaises(ValidationError), self.cr.savepoint():
                    self._project(file_name=filename)

    def test_html_extensions_case_insensitive(self):
        for filename in ('proyecto.html', 'proyecto.htm', 'proyecto.HTML', 'proyecto.HTM'):
            with self.subTest(filename=filename):
                self._project(file_name=filename)

    def test_decoded_size_limit(self):
        with patch.object(installation_project, 'MAX_FILE_SIZE', 4):
            self._project(file_data=base64.b64encode(b'1234'))
            with self.assertRaises(ValidationError), self.cr.savepoint():
                self._project(file_data=base64.b64encode(b'12345'))

    def test_validation_on_write(self):
        project = self._project()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            project.write({'file_name': 'proyecto.pdf'})
        with patch.object(installation_project, 'MAX_FILE_SIZE', 4):
            with self.assertRaises(ValidationError), self.cr.savepoint():
                project.write({'file_data': base64.b64encode(b'12345')})

    def test_protected_fields_require_draft(self):
        project = self._project()
        project.write({'partner_id': self.other_partner.id})
        self.assertEqual(project.partner_id, self.other_partner)
        project.action_send()
        for state in ('sent', 'accepted', 'rejected'):
            project.write({'state': state})
            for values in (
                {'partner_id': self.partner.id},
                {'file_name': 'otro.htm'},
                {'file_data': base64.b64encode(b'<html>Otro</html>')},
                {'file_data': False},
                {'state': 'draft', 'partner_id': self.partner.id},
            ):
                with self.subTest(state=state, values=values):
                    with self.assertRaisesRegex(UserError, 'Vuelve el proyecto a borrador'):
                        project.write(values)
        project.action_reset_to_draft()
        project.write({
            'partner_id': self.partner.id,
            'file_name': 'otro.htm',
            'file_data': base64.b64encode(b'<html>Otro</html>'),
        })
        self.assertEqual(project.state, 'draft')
        self.assertEqual(project.partner_id, self.partner)

    def test_send_requires_document(self):
        project = self._project(file_data=False, file_name=False)
        with self.assertRaises(UserError):
            project.action_send()
        self.assertEqual(project.state, 'draft')

    def test_send_only_transitions_draft(self):
        project = self._project()
        project.action_send()
        self.assertEqual(project.state, 'sent')
        for state in ('sent', 'accepted', 'rejected'):
            project.write({'state': state})
            project.action_send()
            self.assertEqual(project.state, state)

    def test_accept_reject_only_from_sent(self):
        for action, target in (
            ('action_mark_accepted', 'accepted'),
            ('action_mark_rejected', 'rejected'),
        ):
            project = self._project()
            for state in ('draft', 'accepted', 'rejected'):
                project.write({'state': state})
                with self.subTest(action=action, state=state):
                    with self.assertRaises(UserError):
                        getattr(project, action)()
                    self.assertEqual(project.state, state)
            project.write({'state': 'sent'})
            getattr(project, action)()
            self.assertEqual(project.state, target)
