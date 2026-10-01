# RMS Etiqueta Código de Barras (Número de Serie)

Convierte el número de serie de una pieza (cuando el producto no trae
código de barras de fábrica) en un código de barras Code128 imprimible en
una etiqueta de **10x5 cm**, lista para pegar en la pieza y escanear
después con lector físico o con la cámara del móvil
(`rms_stock_barcode_scan`).

## Requisito previo en el producto

En el producto, pestaña **Inventario**, el campo **Trazabilidad** debe
estar en **"Por números de serie únicos"** (o "Por números de lote" si
aplicara). Si está en "Sin seguimiento", Odoo no deja crear números de
serie para ese producto y este módulo no tiene nada que imprimir.

## Flujo de uso (un clic para imprimir)

1. Desde el producto, botón **"Números de serie/Lotes"** (o Inventario >
   Trazabilidad > Números de serie/Lotes), se crea un registro nuevo y se
   escribe a mano el número de serie que trae la pieza físicamente.
2. Se guarda.
3. En el propio formulario del número de serie, menú **Imprimir** →
   **"Etiqueta código de barras (10x5cm)"**.
4. Se abre la vista previa en PDF con: nombre del producto, el código de
   barras (Code128 del número de serie) y el número de serie en texto
   debajo. Al aceptar la impresión desde el navegador (icono de imprimir
   del visor de PDF, o Ctrl+P) se envía a la impresora que tengáis
   configurada/seleccionada.
5. Se pega la etiqueta en la pieza y se continúa con el proceso normal
   (recepción, ubicación, picking, inventario físico...).

También se puede seleccionar varios números de serie a la vez desde la
vista de lista y usar el mismo menú Imprimir para generar todas las
etiquetas en un único PDF (una por página).

## Por qué no hace falta tocar el módulo de escaneo

El código impreso **es literalmente el número de serie** codificado en
Code128 (admite letras y números, no como un EAN). El módulo
`rms_stock_barcode_scan` ya trata cualquier código detectado por la
cámara como el número de serie sin comprobar que coincida con el campo
`barcode` del producto, así que la etiqueta generada aquí se lee sin
ningún cambio adicional.

## Impresora: cómo conectar

Este módulo **no requiere IoT Box**. Usa el sistema estándar de informes
de Odoo: genera un PDF y el navegador abre su diálogo de impresión, que
envía el trabajo a la impresora que el sistema operativo tenga
configurada (por defecto o elegida en ese momento). Esto funciona con
**cualquier impresora de etiquetas que tenga driver instalado** en el
ordenador/tablet (Windows, macOS o Linux) — no hace falta que hable ZPL
ni estar en la misma red que el servidor Odoo.

Si más adelante queréis imprimir en una etiquetadora de red sin pasar por
el diálogo de impresión del navegador (por ejemplo varios puestos
imprimiendo directamente a una Zebra por IP), hace falta añadir una IoT
Box de Odoo o un pequeño conector que envíe ZPL por socket — es una
ampliación de este mismo módulo, no un cambio de planteamiento.

### Impresora recomendada

Para etiquetas de 10x5 cm sin diseño gráfico complejo, en un almacén, con
impresión "un clic" vía driver estándar:

- **Zebra ZD230d / GC420d** (térmica directa, USB): opción recomendada.
  Sin coste de tinta/tóner (térmica directa), driver oficial para
  Windows/macOS, muy extendida en almacenes, soporta 10x5cm sin problema,
  y si en el futuro se quiere pasar a impresión en red sin diálogo del
  navegador, este mismo modelo soporta ZPL y una IoT Box de Odoo.
- **Alternativa más económica: Brother QL-1100**. Usa rollos continuos
  DK de hasta 103mm de ancho (corta a la medida de la etiqueta), driver
  Windows/macOS estándar, buena opción si el volumen de etiquetado es
  bajo/medio.

## Diseño de la etiqueta: cómo editarlo más adelante

La plantilla vive en `report/stock_lot_label_templates.xml` como un QWeb
estándar de Odoo (no HTML generado por Python), así que se puede editar
sin tocar lógica: añadir el logo de la empresa, cambiar tipografías,
mover el texto, etc. Se puede editar directamente el XML o, si tenéis
Odoo Studio, desde el editor visual de informes.

## Instalación

1. Copia la carpeta `rms_stock_lot_label_print` al `addons-path`, junto
   al resto de módulos `rms_*`.
2. Actualiza la lista de aplicaciones e instala **RMS Etiqueta Código de
   Barras (Número de Serie)**.
3. Comprueba que la impresora de etiquetas tiene su driver instalado en
   el ordenador/tablet desde el que se va a imprimir, con el tamaño de
   papel personalizado 100x50mm configurado si el driver lo pide.
