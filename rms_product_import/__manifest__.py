{
    'name': 'RMS Product Import',
    'version': '1.0',
    'category': 'Inventory/Inventory',
    'summary': 'Smart Wizard to import products from Excel with hierarchical categories and state handling.',
    'description': """
        Smart Product Import Wizard:
        - Hierarchical category creation: Brand > Family > Subfamily.
        - Prefix handling for product state (Nuevo, 2 Mano, Demo).
        - Supplier auto-creation and mapping.
        - Attribute handling (2MV, Estado).
    """,
    'author': 'Antigravity',
    'website': 'https://xtendoo.es',
    'depends': ['product', 'purchase', 'stock'],
    'data': [
        'security/ir.model.access.csv',
        'wizard/product_import_wizard_view.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
