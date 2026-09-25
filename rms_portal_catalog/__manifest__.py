{
    'name': 'RMS Portal Catalog',
    'version': '19.0.1.10.0',
    'category': 'Sales',
    'summary': 'Publica el catálogo B2B (HTML estático) en el portal de clientes.',
    'description': """
        Sirve el catálogo estático de productos (HTML + imágenes) en
        /my/catalog y añade una sección "Catálogo" en el portal de clientes.
        El catálogo en sí se empaqueta como archivo estático del propio
        módulo. Incluye además un modelo ligero (rms.catalog.card) para que
        usuarios internos asignen productos de Odoo a cada ficha del
        catálogo, reutilizando el selector nativo "Catálogo de productos".
    """,
    'author': 'Antigravity',
    'depends': ['portal', 'product', 'sale'],
    'data': [
        'security/ir.model.access.csv',
        'views/catalog_card_views.xml',
        'views/portal_templates.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'AGPL-3',
}
