# -*- coding: utf-8 -*-
{
    'name': 'RMS Recepción de proveedor con lista de números de serie',
    'version': '19.0.1.3.0',
    'category': 'Inventory/Inventory',
    'summary': (
        'Recepción de mercancía con la pistola como una lista de la compra: '
        'cada caja leída pone en verde su línea; al cerrar entra en el stock.'
    ),
    'description': """
Recepción de proveedor con checklist de números de serie
=========================================================

- Inventario > Recepción de proveedor > Recepciones: se crea la recepción (proveedor, almacén, referencia del documento).
- "Cargar documento del proveedor": PDF con texto (Meyer Sound, DiGiCo, Luminex, DSPecialists/Harvey o genérico), Excel/CSV eligiendo columnas o texto pegado. Siempre con una vista previa que se puede corregir.
- "Abrir lista": pantalla para iPad o portátil. Cada lectura de la pistola pone en verde su línea. Ámbar = a revisar, rojo = sobrante, gris = código de producto (no cuenta).
- Los números de serie leídos también cuentan en líneas por cantidad sin serie en la lista para productos con seguimiento.
- Una lectura nunca se pierde en silencio: cada lectura se guarda en el aparato hasta que el servidor la confirma (sin conexión, error del servidor o sesión caducada se reintenta sola y se ve como «Pendiente de enviar»); reenviarla no la duplica. No se puede pulsar "He terminado" con lecturas sin enviar o con error.
- "He terminado": pasa a revisión. El responsable decide faltantes, sobrantes y dañados y pulsa "Dar entrada en stock": se crea y valida el albarán de entrada solo con lo recibido y aprobado.
    """,
    'author': 'Custom RMS',
    'website': 'https://xtendoo.es',
    'license': 'LGPL-3',
    # rms_stock_count_session: reglas de lectura por marca, limpieza de
    # códigos y acción de impresión de etiqueta (se reutilizan, no se tocan).
    # rms_scan_queue: cola de lecturas común a las pantallas de pistola.
    'depends': [
        'stock', 'web', 'rms_product_state', 'rms_stock_lot_label_print', 'rms_stock_count_session',
        'rms_scan_queue',
    ],
    'data': [
        'security/reception_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'report/reception_report.xml',
        'wizard/load_document_views.xml',
        'views/reception_views.xml',
        'views/supplier_code_views.xml',
        'views/menus.xml',
        'views/picking_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'rms_stock_reception_check/static/src/checklist/**/*',
        ],
    },
    'installable': True,
    'application': False,
}
