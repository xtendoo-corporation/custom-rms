# -*- coding: utf-8 -*-

{
    'name': 'RMS Sale Category Product Managers',
    'version': '19.0.1.0.0',
    'category': 'Sales/Sales',
    'summary': 'Subscribe product category product managers to quotations automatically.',
    'description': """
        Adds product managers to product categories and automatically subscribes
        them as followers of quotations containing products from those categories.
    """,
    'author': 'Custom RMS',
    'depends': ['sale_management', 'product', 'stock'],
    'data': [
        'views/product_category_views.xml',
        'views/product_template_views.xml',
        'views/sale_order_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
