# -*- coding: utf-8 -*-
{
    'name': 'RMS Restricción Ficha Comerciales',
    'version': '19.0.1.0.0',
    'category': 'Sales',
    'summary': 'Comerciales ven listados pero no pueden abrir fichas de cliente/producto',
    'author': 'Custom RMS',
    'depends': ['base', 'contacts', 'product'],
    'data': [
        'views/res_partner_views.xml',
        'views/product_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
