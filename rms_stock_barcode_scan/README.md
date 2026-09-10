# RMS Stock Barcode Scan (Cámara)

Escanea números de serie con la cámara del móvil/tablet y los añade como
líneas contadas en el **Inventario físico** de Odoo (`stock.quant`), sin
necesidad de un lector de código de barras físico.

## Flujo

1. Menú **Inventario > Escanear código de barras**.
2. **Catálogo**: buscas y eliges un producto (por nombre, referencia o
   código de barras) y confirmas la ubicación de almacén que estás
   contando (por defecto, la ubicación de stock del almacén de tu
   compañía).
3. **Cámara**: se activa la cámara del dispositivo. Sobre la imagen hay un
   recuadro blanco que se puede mover y redimensionar (arrastrando su
   asa); solo se decodifica lo que quede dentro de ese recuadro, lo que
   evita leer por error otro código de barras cercano en la misma
   etiqueta o caja. También hay un control de zoom. Cada código de barras
   nuevo detectado dentro del recuadro se añade a una lista en pantalla
   (con vibración/pitido de confirmación); se puede borrar una lectura
   equivocada antes de terminar.
4. **Confirmar**: al pulsar "Confirmar y añadir al Inventario físico", por
   cada número de serie de la lista:
   - se busca o crea el número de serie (`stock.lot`) de ese producto;
   - se busca o crea la línea de `stock.quant` (producto + lote +
     ubicación) y se le suma **+1** a la cantidad "Contada"
     (`inventory_quantity`).
   No se pulsa "Aplicar todo" automáticamente: las líneas quedan
   pendientes en Inventario físico exactamente igual que si se hubieran
   editado a mano, para que quien hace el recuento revise antes de
   aplicar.

## Supuestos que hay que verificar en vuestra instalación

- **Modelo destino**: se asume que "Inventario físico" es la pantalla
  estándar de Odoo sobre `stock.quant` (Producto / Nº de lote-serie /
  Stock real / Contado / Diferencia). Si en vuestro Odoo es otra cosa,
  hay que ajustar `models/stock_barcode_scan.py`.
- **Ubicación con permiso de escritura del stock.quant**: la creación/edición
  de líneas requiere que el usuario tenga los mismos permisos que ya
  necesita para editar "Contado" a mano en esa pantalla.
- El botón se ha añadido como **entrada de menú propia** dentro de la app
  Inventario (Inventario > Escanear código de barras), no embebido dentro
  de la vista de Inventario físico en sí: para injertarlo literalmente ahí
  hace falta el id técnico exacto de esa vista/acción en vuestra
  instalación (Modo desarrollador > esa pantalla > Ver metadatos), que no
  se puede adivinar sin riesgo de romper la instalación del módulo con un
  `inherit_id` incorrecto.

## Cámara: compatibilidad

- Usa la **Barcode Detection API** nativa del navegador cuando existe
  (Chrome/Android). Si no está disponible (Safari/iOS, Firefox de
  escritorio...), carga automáticamente una librería de reserva
  ([ZXing](https://github.com/zxing-js/library), incluida dentro del
  propio módulo en `static/lib/zxing/`, sin llamadas a internet) que
  decodifica el vídeo igualmente.
- Requiere **HTTPS** (o `localhost`) y que el usuario conceda permiso de
  cámara al navegador.
- Formatos reconocidos: EAN-13, EAN-8, UPC-A, UPC-E, Code128, Code39, ITF,
  QR.
- **Zoom**: si el dispositivo/navegador expone zoom óptico/digital nativo
  de la cámara (Android/Chrome, según el móvil), el slider lo controla
  directamente. Si no (iOS Safari no permite controlar el zoom de la
  cámara desde el navegador), se aplica un zoom digital por CSS sobre la
  imagen mostrada — ayuda a ver mejor el código, pero no mejora la
  resolución real capturada.

## Instalación

1. Copia la carpeta `rms_stock_barcode_scan` a vuestro `addons-path` junto
   al resto de módulos `rms_*`.
2. Actualiza la lista de aplicaciones e instala **RMS Stock Barcode Scan
   (Cámara)**.
3. El menú aparece dentro de la app **Inventario**, visible para el grupo
   `stock.group_stock_user`.
