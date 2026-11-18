{
    'name': 'RMS - Promociones en ventas',
    'version': '19.0.1.1.1',
    'category': 'Sales',
    'summary': 'El producto de regalo de las promociones queda siempre al 100 % de descuento, también para los comerciales sin permiso de descuentos y con el triple descuento',
    'author': 'Custom RMS',
    'license': 'LGPL-3',
    'depends': [
        'sale_loyalty',
        'product_pricelist_triple_discount',
        'rms_ventas_restriccion_comerciales',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/sale_order_views.xml',
        'views/loyalty_program_views.xml',
        'wizard/sale_loyalty_reward_wizard_views.xml',
    ],
    'auto_install': True,
    'installable': True,
}
