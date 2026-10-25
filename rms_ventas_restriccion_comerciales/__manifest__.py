# -*- coding: utf-8 -*-
{
    'name': 'RMS Restricción Ficha Comerciales',
    'version': '19.0.1.2.2',
    'category': 'Sales',
    'summary': 'Comerciales ven listados pero no pueden abrir fichas de cliente/producto, ver listas de precios ni cambiar precios, descuentos e impuestos',
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
    'application': False,
    'license': 'LGPL-3',
}
