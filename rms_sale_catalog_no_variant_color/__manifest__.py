# -*- coding: utf-8 -*-
{
    'name': 'RMS Sale Catalog No Variant Color',
    'version': '1.0',
    'category': 'Sales',
    'summary': 'Elimina el color diferencial de las variantes de producto en la vista del catálogo del presupuesto.',
    'description': """
Este módulo hereda la vista kanban del catálogo de productos (usada al agregar líneas a un presupuesto/pedido)
y elimina la opción 'color_field' de las etiquetas de las variantes de producto. De este modo, todas las
variantes se muestran con un estilo y color neutro y uniforme.
    """,
    'author': 'Antigravity',
    'depends': [
        'product',
        'sale',
    ],
    'data': [
        'views/product_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
