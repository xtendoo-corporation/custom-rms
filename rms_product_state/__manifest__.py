{
    'name': 'RMS Product States',
    'version': '19.0.1.0.0',
    'summary': 'Manage custom product states (New, Demo, Ex-Demo, Second Hand, Discontinued) and lot pricing rules.',
    'description': """
This module adds a product state classification to Odoo.
It controls lot-level pricing and discounts, blocks demo item sales,
and automates the archiving of discontinued products with depleted stock.
    """,
    'category': 'Sales/Inventory',
    'author': 'RMS Pro Audio',
    'website': 'https://www.rmsproaudio.com',
    'depends': [
        'product',
        'stock',
        'sale_stock',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/product_state_data.xml',
        'data/ir_cron_data.xml',
        'views/product_state_views.xml',
        'views/product_template_views.xml',
        'views/stock_lot_views.xml',
        'views/sale_order_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
