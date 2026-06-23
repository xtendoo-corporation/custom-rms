{
    'name': 'RMS Custom Knowledge',
    'version': '19.0.5.0.0',
    'category': 'Knowledge',
    'summary': 'Extends Documents Knowledge with folders and PDF to Markdown rendering.',
    'description': """
        Extension for document_knowledge that adds hierarchical knowledge
        directories and automatic PDF to Markdown conversion on attachments.
    """,
    'author': 'Antigravity',
    'depends': ['document_knowledge', 'mail', 'web'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/document_knowledge_category_data.xml',
        'views/document_knowledge_category_views.xml',
        'views/ir_attachment_views.xml',
        'views/res_users_views.xml',
        'views/menu_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'rms_custom_knowledge/static/src/css/knowledge_kanban.css',
            'rms_custom_knowledge/static/src/js/knowledge_binary_field.js',
            'rms_custom_knowledge/static/src/js/knowledge_subdirectory_one2many.js',
            'rms_custom_knowledge/static/src/xml/knowledge_binary_field.xml',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'AGPL-3',
}
