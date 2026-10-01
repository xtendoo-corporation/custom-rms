# -*- coding: utf-8 -*-
{
    'name': 'RMS Etiqueta Código de Barras (Número de Serie)',
    'version': '19.0.1.0.0',
    'category': 'Inventory/Inventory',
    'summary': (
        'Genera e imprime una etiqueta de 10x5cm con el código de barras '
        'del número de serie, para productos que no traen código de '
        'barras de fábrica.'
    ),
    'description': """
Etiqueta de código de barras a partir del número de serie
===========================================================

Muchos productos entran en el almacén con número de serie pero sin
código de barras de fábrica. Este módulo permite convertir ese número de
serie en un código de barras (Code128) imprimible en una etiqueta de
10x5cm, para poder inventariarlo y moverlo con lector/cámara igual que un
producto que sí trae código de barras.

Flujo:

1. En el producto, pestaña "Inventario", el rastreo debe estar puesto
   como "Por números de serie únicos" (si no, Odoo no permite crear
   números de serie para ese producto).
2. Desde el producto (botón "Números de serie/Lotes") o desde
   Inventario > Trazabilidad > Números de serie/Lotes, se crea un nuevo
   registro y se escribe a mano el número de serie que trae la pieza.
3. Se guarda el registro y, en el propio formulario, se abre el menú
   "Imprimir" y se elige "Etiqueta código de barras (10x5cm)".
4. Se abre la vista previa del PDF con la etiqueta (nombre del producto +
   código de barras Code128 + número de serie en texto). Al confirmar la
   impresión desde el navegador (Ctrl+P / icono de imprimir) se envía a
   la impresora de etiquetas configurada como destino.
5. Se pega la etiqueta en la pieza y se continúa con el proceso habitual
   (recepción, ubicación, picking, inventario físico...). El módulo de
   escaneo con cámara (rms_stock_barcode_scan) ya lee ese código de
   barras como el número de serie sin ningún cambio adicional.

Notas:
- El código de barras impreso es el propio número de serie codificado en
  Code128 (admite letras y números), no un EAN. Si el producto ya tiene
  un código de barras de fábrica válido, no hace falta usar este módulo.
- La plantilla del informe es un QWeb estándar de Odoo: se puede editar
  más adelante (añadir logo, cambiar tipografía, etc.) sin tocar el
  código Python, desde el editor de informes o Estudio de Odoo.
- No requiere IoT Box: usa el sistema de impresión de informes estándar
  de Odoo (vista previa en PDF + diálogo de impresión del navegador), por
  lo que funciona con cualquier impresora de etiquetas que tenga driver
  instalado en el ordenador/tablet (Windows, macOS o Linux).
    """,
    'author': 'Custom RMS',
    'website': 'https://xtendoo.es',
    'license': 'LGPL-3',
    'depends': ['base', 'web', 'stock'],
    'data': [
        'report/label_paperformat.xml',
        'report/stock_lot_label_templates.xml',
        'report/stock_lot_label_report.xml',
    ],
    'installable': True,
    'application': False,
}
