# RMS Recuento cruzado (varios operarios)

Varias personas recorren el almacén a la vez (cada una por su lado) con una
PDA o un móvil, escaneando todo lo que ven. Al terminar, Odoo cruza las
lecturas de todos con el stock: lo que se le pasó a uno, normalmente lo vio
el otro.

## Flujo

1. **Inventario > Operaciones > Recuento cruzado > Nuevo**: se elige la
   ubicación a recontar (cuenta también todas sus sububicaciones).
2. **Abrir escáner** en cada PDA/móvil. Cada operario escribe su nombre (o
   pulsa el suyo si ya había entrado) y empieza a escanear. Se identifica por
   nombre, así que dos PDAs con el mismo usuario de Odoo cuentan como dos
   operarios.
3. Escaneo libre, sin elegir antes el producto. Cada código se interpreta así:
   1. **Etiqueta de ubicación** (campo "Código de barras" de la ubicación):
      cambia la ubicación actual del operario.
   2. **Código de barras o referencia interna de un producto**:
      - sin seguimiento: cuenta **1 unidad** por lectura;
      - con nº de serie/lote: fija el **producto actual** y espera su nº de serie.
   3. **Número de serie/lote que ya existe en Odoo**: cuenta esa unidad.
   4. Código nuevo con un producto actual con seguimiento: **nº de serie
      nuevo** de ese producto (se crea al volcar).
   5. Si no, **sin identificar**: se asigna en la revisión. También se puede
      elegir el producto a mano en el botón del cubo antes de escanear sus
      números de serie (marcas sin EAN en la caja).

   Se quitan prefijos como `S/N:`, `SN ` o `Serial No.` y los caracteres de
   control que añaden algunos lectores. Un número de serie leído dos veces por
   el mismo operario no cuenta doble (aviso de "duplicado").
4. Cada lectura se **guarda en el servidor al momento**. Si se cae la Wi-Fi,
   las lecturas esperan en la PDA y se reenvían solas al volver la conexión,
   sin duplicarse. Arriba se ve cuántas lecturas lleva cada compañero.
5. **Sin etiqueta**: para un equipo con el nº de serie grabado en la placa (sin
   caja original), con la etiqueta dañada o en una caja con varios equipos. Abre
   la etiqueta sustituta (`rms_stock_lot_label_print`) con el producto actual: se
   escribe el nº de serie (dos veces si es uno), se da de alta, se imprime la
   etiqueta y queda contado en el recuento para ese operario.
6. Cada operario pulsa **He terminado mi recorrido**. El responsable pulsa
   **Terminar recuento y cruzar**.

## Reglas de lectura y códigos alternativos

- **Inventario > Configuración > Reglas de lectura de etiquetas**: códigos que se
  ignoran (transporte, cantidades, URLs...) y cómo extraer el número de serie
  cuando el fabricante lo codifica con prefijos o en otro formato. Se aplican
  antes de buscar en Odoo y se pueden editar sin tocar código.
- **Códigos alternativos de producto** (pestaña Inventario del producto, o
  Inventario > Configuración > Productos): referencias del fabricante que
  identifican el producto al escanearlas. Se comparan sin espacios, guiones ni
  puntos, igual que la referencia interna. En la revisión de un recuento, el
  botón **"Es el código del producto"** las da de alta solas.
- Los EAN/UPC se buscan en sus dos formas (12 y 13 cifras), y un ITF-14 de caja
  (p. ej. caja de 2 Atlas FC-4T) se reconoce como el producto sin contar unidad.
- Los números de serie se comparan también sin espacios y, si son solo cifras,
  sin ceros a la izquierda.
- Si una referencia corresponde a varias variantes "Estado" del mismo producto
  (las que crea `rms_product_import`), se usa la que ya estuviera usando el
  operario o la de "Nuevo".

### Etiquetas revisadas (fotos del almacén, octubre 2026)

| Marca | Nº de serie | Producto | A tener en cuenta |
|---|---|---|---|
| Meyer Sound | 8 cifras en Code39 (`26375439`) | Ref. `09.336.001.02` solo impresa | Kits con hoja de 10 pegatinas de nº de serie (MTC-X40); en algunos el nº de serie va en pegatina **sin código de barras** (MUB-X40). En equipos antiguos sin caja, el nº de serie solo está grabado en la placa del equipo (Leopard): **etiqueta sustituta** |
| DiGiCo / KLANG | Code39 (`KNA15797`, `164-W-L-100136`, `215466 2301` = 6 cifras + año/mes; se busca con o sin espacio) | Part number en Code39 (`X-A-164-W-L`) + EAN | Cantidad en código de barras (`01`), pegatina `A41…C…` que no es el nº de serie, QR de reciclaje |
| Sony | Code39 `S01-NNNNNNN-X` | `P-NNNNNNNN-X` + EAN "POS" | Cajas de kit UWP-D con `S01-0000000` (sin nº de serie) y lista de nº de serie de cada transmisor/receptor; etiqueta SSCC de transporte |
| Auvitran | Impreso (`S/N: 001255`), sin código de barras | EAN-13 | El QR lleva el S/N en hexadecimal (`FF01140004E7` = 001255) |
| Luminex | Code128 / QR `LUM…` | Model no. en Code128 con espacios (`LU 01 00072`) | Dos códigos en la misma etiqueta (modelo y nº de serie) |
| AtlasIED | Code128 `SN` + 2 letras + 15 cifras | UPC; ITF-14 en cajas de varias unidades | Caja de 2 FC-4T con 2 nº de serie |
| Neutrik | 10 cifras (`1097451011`) | EAN + referencia Code39 | Caja de 10 con 10 nº de serie; "PCS 10" en código de barras |
| Sound Devices | Code128 12 caracteres (`AA0625052008`) | EAN-13 | Etiqueta limpia: un código de cada |
| Williams AV | Code128 `BS01…` (nº de serie del sistema) | UPC | Kit (1 TX + 2 RX) con un nº de serie de caja |
| Optocore | Impreso (`SN: X94-2353`), sin código de barras | Impreso | Hay que escribirlo a mano |

## Informe de cruce

| Resultado | Significado | ¿Se vuelca por defecto? |
|---|---|---|
| Coincide | Lo vieron todos (y en la misma cantidad) | Sí |
| Solo lo vio una parte | Algún operario no lo escaneó: revisar | Sí (cuenta 1 / la mayor cantidad) |
| Cantidades distintas | Todos lo vieron pero contaron cantidades diferentes | Sí (la mayor cantidad) |
| Nuevo (no estaba en Odoo) | Lo vieron todos y Odoo no lo tenía aquí | Sí |
| Nadie lo escaneó | Odoo lo tiene en stock aquí y nadie lo vio | **No**: márcalo solo si confirmas que falta (se cuenta a 0) |

- Si un nº de serie aparece en otra ubicación del recuento distinta a la de
  Odoo, se propone la ubicación donde se escaneó y, al volcar, la antigua
  queda contada a 0.
- Pestaña **Sin identificar**: se indica el producto de cada código y se pulsa
  "Asignar" (el cruce se regenera solo), o se marca "Ignorar" si no es de
  producto (MAC, modelo, etiqueta de transporte...).
- **Imprimir cruce** genera el PDF del informe.

## Volcado

**Volcar a Inventario físico** pasa las líneas marcadas a la cantidad
"Contada" de Inventario físico (`stock.quant`). **No aplica el ajuste**: las
diferencias quedan pendientes en Inventario físico para revisarlas y pulsar
"Aplicar", igual que con `rms_stock_barcode_scan`.

## Dependencias

- `rms_stock_barcode_scan`: se reutiliza su copia de ZXing para la cámara en
  navegadores sin `BarcodeDetector` (Safari/iOS).
- La cámara necesita HTTPS. El modo **PDA** funciona con cualquier lector en
  modo teclado que envíe Enter al final.
