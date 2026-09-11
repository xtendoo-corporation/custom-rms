# -*- coding: utf-8 -*-
{
    'name': 'RMS Stock Barcode Scan (Cámara)',
    'version': '19.0.1.0.0',
    'category': 'Inventory/Inventory',
    'summary': (
        'Escanea números de serie con la cámara del móvil y añade las '
        'unidades contadas al Inventario físico (stock.quant).'
    ),
    'description': """
Escaneo de números de serie con la cámara del móvil
=====================================================

Flujo:

1. Menú "Inventario > Escanear código de barras" abre un asistente a
   pantalla completa.
2. Paso 1 (catálogo): buscas y seleccionas un producto (por nombre,
   referencia o código de barras) y confirmas la ubicación de almacén
   donde estás contando.
3. Paso 2 (cámara): se abre la cámara del móvil/tablet y cada código de
   barras nuevo que detecta (el número de serie que va debajo del propio
   código) se añade a una lista en pantalla, con aviso sonoro y de
   vibración. Se pueden borrar lecturas erróneas antes de terminar.
4. Paso 3 (confirmar): revisas la lista y, al confirmar, por cada número
   de serie escaneado:
   - se busca o crea el lote/nº de serie (stock.lot) para ese producto;
   - se busca o crea la línea de stock.quant (producto + lote + ubicación)
     y se incrementa en +1 su cantidad "Contada", igual que si se editara
     a mano en Inventario físico.
   No se aplica el ajuste automáticamente: sigue apareciendo pendiente en
   Inventario físico hasta que se pulse "Aplicar todo", igual que ahora.

Notas técnicas / supuestos:
- Asume que la pantalla "Inventario físico" es la vista estándar de Odoo
  sobre stock.quant. Si en vuestra instalación es otra cosa, avisad y se
  ajusta el modelo destino.
- Usa la Barcode Detection API nativa del navegador cuando está
  disponible (Chrome/Android) y, si no, una librería de reserva (ZXing,
  incluida en el propio módulo) para que también funcione en Safari/iOS.
- Requiere permiso de cámara del navegador (HTTPS obligatorio, salvo
  localhost).
- Un número de serie repetido para el mismo producto reutiliza el lote
  existente en vez de duplicarlo.
    """,
    'author': 'Custom RMS',
    'website': 'https://xtendoo.es',
    'license': 'LGPL-3',
    'depends': ['base', 'web', 'stock', 'rms_product_state'],
    'data': [
        'security/ir.model.access.csv',
        'views/stock_barcode_scan_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'rms_stock_barcode_scan/static/src/stock_barcode_scan/**/*',
        ],
    },
    'installable': True,
    'application': False,
}
