import base64

from psycopg2 import IntegrityError

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged
from odoo.tests.common import new_test_user
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestKnowledgeRegressions(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.internal = new_test_user(
            cls.env, login='knowledge_internal_w2c', groups='base.group_user',
        )
        cls.contributor = new_test_user(
            cls.env, login='knowledge_contributor_w2c',
            groups='base.group_user,rms_custom_knowledge.group_knowledge_contributor',
        )
        cls.manager = new_test_user(
            cls.env, login='knowledge_manager_w2c',
            groups='base.group_user,rms_custom_knowledge.group_knowledge_manager',
        )
        cls.restricted = cls.env['document.knowledge.category'].create({
            'name': 'Directorio restringido W2C',
        })
        cls.access_line = cls.env['document.knowledge.access'].create({
            'category_id': cls.restricted.id,
            'group_id': cls.env.ref('rms_custom_knowledge.group_knowledge_manager').id,
            'permission': 'delete',
        })
        cls.document = cls.env['ir.attachment'].create({
            'name': 'Documento privado W2C.txt',
            'datas': base64.b64encode(b'Privado'),
            'is_knowledge_document': True,
            'knowledge_category_id': cls.restricted.id,
        })
        cls.general = cls.env.ref(
            'rms_custom_knowledge.document_knowledge_category_general',
        )
        cls.public_document = cls.env['ir.attachment'].create({
            'name': 'Documento general W2C.txt',
            'datas': base64.b64encode(b'General'),
            'is_knowledge_document': True,
            'knowledge_category_id': cls.general.id,
        })

    def test_markdown_preview_sanitizes_raw_html(self):
        # La extensión extra conserva HTML crudo; la preview debe sanearlo.
        attachment = self.env['ir.attachment'].create({
            'name': 'preview-w2c.md',
            'mimetype': 'text/markdown',
            'datas': base64.b64encode(
                b'# Contenido\n\n<img src=x onerror="alert(1)">',
            ),
            'is_knowledge_document': True,
            'knowledge_category_id': self.general.id,
        })
        self.assertIn('Contenido', attachment.body_html)
        self.assertNotIn('onerror', attachment.body_html.lower())
        self.assertNotIn('onerror', attachment._get_textual_preview_body().lower())

    def test_contributor_search_count_and_read_group(self):
        domain = [('id', 'in', (self.document | self.public_document).ids)]
        attachments = self.env['ir.attachment'].with_user(self.contributor).with_context(
            rms_knowledge_mode=True,
        )
        self.assertEqual(attachments.search_count(domain), 1)
        self.assertEqual(attachments.search(domain), self.public_document)
        groups = attachments.read_group(domain, ['name'], ['name'], lazy=False)
        self.assertEqual([group['name'] for group in groups], [self.public_document.name])
        # Los gestores conservan la visibilidad global.
        self.assertEqual(attachments.with_user(self.manager).search_count(domain), 2)

    def test_internal_reads_only_accessible_permissions(self):
        readable_line = self.env['document.knowledge.access'].create({
            'category_id': self.general.id,
            'group_id': self.env.ref('base.group_user').id,
            'permission': 'read',
        })
        access = self.env['document.knowledge.access'].with_user(self.internal)
        self.assertFalse(access.search([('id', '=', self.access_line.id)]))
        with self.assertRaises(AccessError):
            self.access_line.with_user(self.internal).read(['permission'])
        self.assertTrue(readable_line.with_user(self.internal).read(['permission']))
        self.assertTrue(self.access_line.with_user(self.manager).read(['permission']))

    def test_duplicate_category_group_is_rejected(self):
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'):
            with self.env.cr.savepoint():
                self.env['document.knowledge.access'].create({
                    'category_id': self.restricted.id,
                    'group_id': self.access_line.group_id.id,
                    'permission': 'read',
                })
                self.env.flush_all()

    def test_init_does_not_update_already_clean_attachments(self):
        attachment = self.env['ir.attachment'].create({
            'name': 'Adjunto ajeno a Knowledge W2C',
        })
        self.env.flush_all()
        # Simular un dato legado sin pasar por la normalización de create/write.
        self.env.cr.execute(
            'UPDATE ir_attachment SET knowledge_category_id = %s WHERE id = %s',
            [self.general.id, attachment.id],
        )
        attachments = self.env['ir.attachment']
        attachments.init()
        self.env.cr.execute(
            'SELECT knowledge_category_id FROM ir_attachment WHERE id = %s',
            [attachment.id],
        )
        self.assertFalse(self.env.cr.fetchone()[0])
        attachments.init()
        self.assertEqual(self.env.cr.rowcount, 0)
        self.env.cr.execute(
            'SELECT knowledge_category_id FROM ir_attachment WHERE id = %s',
            [self.document.id],
        )
        self.assertEqual(self.env.cr.fetchone()[0], self.restricted.id)
