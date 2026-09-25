{
    'name': 'RMS Portal Catalog',
    'version': '19.0.1.8.0',
    'category': 'Sales',
    'summary': 'Publica el catálogo B2B (HTML estático) en el portal de clientes.',
    'description': """
        Sirve el catálogo estático de productos (HTML + imágenes) en
        /my/catalog y añade una sección "Catálogo" en el portal de clientes.
        No depende de ningún modelo: el catálogo se empaqueta como archivo
        estático del propio módulo.
    """,
    'author': 'Antigravity',
    'depends': ['portal'],
    'data': [
        'views/portal_templates.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'AGPL-3',
}
