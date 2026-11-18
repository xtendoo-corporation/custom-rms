{
    'name': 'RMS Checklist de salida con pistola',
    'version': '19.0.1.1.0',
    'category': 'Inventory/Inventory',
    'summary': 'Checklist de salida: cada caja se lee con la pistola y pone en verde su línea '
               'del albarán. Paquetes de 2ª mano y depósitos en clientes (salida y vuelta).',
    'description': """
Checklist de salida con pistola
===============================

* Botón "Abrir checklist" en los albaranes de salida: el operario lee el nº de
  serie de cada caja y la línea se pone en verde. Nada sale sin coincidir
  producto + nº de serie con el albarán y estar en stock en el origen.
* Verde: correcto. Ámbar: lo decide un administrador (estado distinto al
  pedido, nº de serie distinto al fijado, paquete de 2ª mano incompleto, 2ª
  mano sin paquete autorizado). Rojo: bloqueado (Demo en una venta, no está en
  el albarán, no está en stock, ya salió). Gris: código de producto / EAN.
* Ex-Demo y 2ª mano: casilla "Revisado" obligatoria por unidad.
* Envío incompleto: lo decide el administrador (con o sin pendiente).
* Paquetes de 2ª mano autorizados por Dirección (rms.used.pack).
* Depósitos en clientes sobre las cesiones (stock_cession): salida y vuelta
  con checklist, y listado de lo que sigue fuera con sus días.
* Documentos PDF de depósito: entrega (firma del cliente) y devolución (firma
  en almacén), una hoja por albarán de vuelta.
* Todas las lecturas quedan guardadas; lo inesperado queda como incidencia.
    """,
    'author': 'Custom RMS',
    'license': 'LGPL-3',
    'depends': ['stock', 'sale_stock', 'rms_product_state', 'stock_cession', 'rms_stock_lot_label_print'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'report/delivery_serials_report.xml',
        'report/deposit_report.xml',
        'views/stock_picking_views.xml',
        'views/delivery_scan_views.xml',
        'views/used_pack_views.xml',
        'views/stock_cession_views.xml',
        'views/sale_order_views.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'rms_stock_delivery_check/static/src/delivery_check/**/*',
        ],
    },
    'installable': True,
    'application': False,
}
