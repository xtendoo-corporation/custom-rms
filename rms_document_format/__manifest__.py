# -*- coding: utf-8 -*-
{
    'name': 'RMS Document Format Customization',
    'version': '1.0',
    'category': 'Sales',
    'summary': 'Añade una nueva plantilla de impresión personalizada para presupuestos',
    'depends': [
        'base',
        'sale',
        'sale_management',
        'web',
        'product_pricelist_triple_discount',
        'sale_global_discount'
    ],
    'data': [
        'views/res_config_settings_views.xml',
        'reports/report_action.xml',
        'reports/report_template.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}