{
    'name': 'Product Pricelist Triple Discount',
    'version': '19.0.1.0.0',
    'category': 'Sales/Sales',
    'summary': 'Añade hasta 3 descuentos por regla de tarifa de producto',
    'description': """
        Permite asignar hasta tres descuentos (discount1, discount2, discount3)
        a cada regla de tarifa. Al introducir cualquier descuento, se activa
        automáticamente el modo porcentaje y se calcula el descuento combinado
        en cascada.
    """,
    'author': 'Custom RMS',
    'depends': ['product', 'sale', 'sale_triple_discount'],
    'data': [
        'views/product_pricelist_views_inherit.xml',
    ],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
