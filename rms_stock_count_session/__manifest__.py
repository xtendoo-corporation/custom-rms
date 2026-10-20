# -*- coding: utf-8 -*-
{
    'name': 'RMS Recuento cruzado (varios operarios)',
    'version': '19.0.1.1.0',
    'category': 'Inventory/Inventory',
    'summary': (
        'Varias personas recorren el almacén escaneando con PDA o móvil y '
        'al terminar se cruzan sus lecturas con el stock de Odoo.'
    ),
    'description': """
Recuento cruzado con varios operarios
======================================

1. Inventario > Operaciones > Recuento cruzado: se crea un recuento
   indicando la ubicación (y sus sububicaciones) que se va a contar.
2. "Abrir escáner" en cada PDA/móvil: cada operario entra con su nombre
   y escanea libremente todo lo que ve (ubicaciones, códigos de producto,
   números de serie). Cada lectura se guarda en el servidor al momento.
3. "Terminar recuento y cruzar": se genera el informe de cruce con lo que
   vieron todos, lo que solo vio una parte, lo que Odoo esperaba y nadie
   escaneó, y lo que se encontró sin estar en Odoo.
4. "Volcar a Inventario físico": las líneas marcadas pasan como cantidad
   contada, sin aplicar el ajuste (se revisa y aplica como siempre).
    """,
    'author': 'Custom RMS',
    'website': 'https://xtendoo.es',
    'license': 'LGPL-3',
    # rms_stock_barcode_scan: se reutiliza su copia de ZXing para leer con
    # la cámara en navegadores sin BarcodeDetector (iOS).
    'depends': ['stock', 'web', 'rms_stock_barcode_scan'],
    'data': [
        'security/ir.model.access.csv',
        'security/stock_count_security.xml',
        'data/ir_sequence_data.xml',
        'data/rms_scan_rule_data.xml',
        'report/stock_count_cross_report.xml',
        'views/stock_count_session_views.xml',
        'views/scan_rule_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'rms_stock_count_session/static/src/count_scan/**/*',
        ],
    },
    'installable': True,
    'application': False,
}
