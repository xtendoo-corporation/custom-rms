# -*- coding: utf-8 -*-
{
    'name': 'RMS Sale Catalog No Variant Color',
    'version': '1.0',
    'category': 'Sales',
    'summary': 'Colorea las variantes de producto por estado en el catálogo del presupuesto y añade el menú Catálogo de Productos (kanban y lista).',
    'description': """
Nota: a pesar del nombre técnico del módulo (que se mantiene para no romper instalaciones existentes),
hoy hace lo contrario de lo que su nombre indica: colorea las etiquetas de variante según su valor
(Nuevo = verde, 2 Mano = amarillo, Demo = naranja, resto = gris) en el catálogo del presupuesto, para
distinguirlas de un vistazo. El botón "Catálogo" del presupuesto incluye además una vista de lista.

Además, añade el menú "Catálogo de Productos" (Ventas > Productos) con vistas de tarjetas (kanban) y de
lista, para poder alternar entre ambos modos de visualización al navegar el catálogo.
    """,
    'author': 'Antigravity',
    'depends': [
        'product',
        'sale',
    ],
    'data': [
        'views/product_views.xml',
        'views/product_catalog_list_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'rms_sale_catalog_no_variant_color/static/src/product_catalog_list/**/*',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
