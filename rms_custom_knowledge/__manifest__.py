{
    'name': 'RMS Custom Knowledge',
    'version': '19.0.1.0.0',
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
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'AGPL-3',
}
