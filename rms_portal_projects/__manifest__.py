{
    'name': 'RMS Portal Projects',
    'version': '19.0.1.4.0',
    'category': 'Sales',
    'summary': 'Comparte PDFs de proyectos de instalación con el cliente a través del portal.',
    'description': """
        Añade un nuevo modelo de Proyectos de Instalación (independiente de la
        app Proyecto nativa de Odoo) y una sección "Proyectos" en el portal de
        clientes, donde cada contacto solo ve los proyectos que se le han
        asignado y enviado.
    """,
    'author': 'Antigravity',
    'depends': ['portal', 'mail'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/installation_project_views.xml',
        'views/portal_templates.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'AGPL-3',
}
