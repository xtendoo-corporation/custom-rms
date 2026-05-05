{
    'name': 'Stock Cession (Gestión de Cesiones)',
    'version': '19.0.1.0.0',
    'category': 'Inventory/Inventory',
    'summary': 'Gestión de mercancía cedida a clientes o en ubicaciones externas',
    'description': """
        Permite registrar cesiones de mercancía.
        Al confirmar, saca el stock de nuestro inventario y lo mueve
        a una ubicación de cliente o virtual, manteniendo la trazabilidad.
    """,
    'author': 'Custom RMS',
    'depends': ['stock'],
    'data': [
        'security/ir.model.access.csv',
        'views/stock_cession_views.xml',
    ],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
