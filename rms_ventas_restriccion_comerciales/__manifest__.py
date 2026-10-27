# -*- coding: utf-8 -*-
{
    'name': 'RMS Restricción Ficha Comerciales',
    'version': '19.0.1.4.0',
    'category': 'Sales',
    'summary': 'Comerciales ven listados pero no pueden abrir fichas de cliente/producto, cambiar listas de precios ni precios, descuentos e impuestos; solo presupuestan a sus propios clientes',
    'author': 'Custom RMS',
    'depends': ['base', 'contacts', 'product', 'sale'],
    'data': [
        'security/res_groups.xml',
        'security/product_security.xml',
        'views/res_partner_views.xml',
        'views/product_views.xml',
        'views/product_category_views.xml',
    ],
    'installable': True,
    'pre_init_hook': 'pre_init_hook',
    'application': False,
    'license': 'LGPL-3',
}
