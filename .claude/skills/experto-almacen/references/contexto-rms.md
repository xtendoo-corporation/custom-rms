# Lo que ya se sabe de RMS Proaudio (octubre 2026)

Punto de partida de la entrevista. Confírmalo si hace falta, pero no lo vuelvas
a preguntar desde cero. Las correcciones posteriores se apuntan en
`docs/requisitos-almacen/entrevista.md`, que manda sobre este fichero.

Fuentes: web de RMS Proaudio y notas de prensa (empresa y marcas), 24 fotos
de etiquetas del almacén tomadas en octubre de 2026 (etiquetas), código del
repositorio `custom-rms` (datos y módulos).

## Empresa

- **RMS Proaudio**, Madrid (Polígono de Vallecas). Razón social según las
  etiquetas de envío de Sony: "Rental Multimedia Sistem SL" (escrito así). Distribuidor de audio profesional para España y, en DiGiCo,
  también Portugal (nota de prensa de DiGiCo, 2022). Más de 20 marcas.
- Marcas de su web: DiGiCo, KLANG, Meyer Sound, Sony (pro audio), Sound
  Devices, Hollyland, Point Source Audio, Remic, Fourier Audio, Luminex,
  Optocore, Auvitran, Waves, Joyned, TeqSAS, CAST BlackTrax, Whirlwind,
  Furman, AtlasIED, Williams AV, D Specialists (HARVEY), Neutrik Fiberfox,
  LINK (LK, Eurocable).
- Mezcla de equipos caros con número de serie (consolas, altavoces, sistemas
  inalámbricos, switches) y material por cantidad (cables, conectores,
  accesorios). Hay **demos, ex-demos y segunda mano**, y equipos cedidos a
  clientes.

## Lo que se vio en las fotos del almacén

- Cajas con **"DEMO" escrito a mano** en cinta de carrocero y **pegatinas
  redondas verdes** (significado desconocido: pregúntalo).
- Pegatina de un inventario anterior: "INVENTARIO: NOVIEMBRE 2023 ·
  CONTABILIZADO · MATERIAL: Nuevo / Demo / 2ª Mano". Había un proceso de
  recuento manual: pregunta cómo fue y qué falló.
- Etiqueta interna de un sistema anterior en una caja Meyer:
  `A-017345-MUB-X40-SOPORTE TIPO U PARA X40` con código `2000000140100`.
- Una caja de Luminex con el número de serie tachado y escrito a mano.
- Equipos antiguos (p. ej. Meyer Leopard de 2009) sin caja: el número de serie
  solo está **grabado en la placa del equipo**.

## Cómo etiqueta cada marca (24 fotos analizadas)

Formatos deducidos de los códigos leídos en las fotos (entre 1 y 10 muestras
por marca). Sony y AtlasIED no publican cómo imprimen el número de serie en el
propio equipo: la etiqueta de la caja es lo único comprobado.

| Marca | Nº de serie | Identificación del producto | Riesgos |
|---|---|---|---|
| Meyer Sound | 8 cifras, Code39 | Ref. `09.336.001.02` solo impresa | Kits con 10 pegatinas de nº de serie; algunas sin código de barras; equipos antiguos solo con placa grabada |
| DiGiCo / KLANG | Code39: `215466 2301` (6 cifras + año/mes), `164-W-L-100136`, `KNA15797` | Part number Code39 (`X-A-164-W-L`) + EAN | Cantidad en código de barras; pegatina `A41…C…` que no es nº de serie; QR de reciclaje |
| Sony | Code39 `S01-NNNNNNN-X` | `P-NNNNNNNN-X` + EAN | Kits UWP-D: caja sin nº de serie y lista de nº de serie de cada transmisor/receptor; SSCC de transporte |
| Auvitran | Solo impreso (`S/N: 001255`) | EAN-13 | El QR codifica el S/N en hexadecimal |
| Luminex | `LUM…` en Code128 y QR | Model no. Code128 con espacios (`LU 01 00072`) | Dos códigos en la misma etiqueta; MAC junto al nº de serie |
| AtlasIED | Code128 `SN` + 2 letras + 15 cifras | UPC; ITF-14 en cajas de varias unidades | Caja de 2 unidades con 2 nº de serie |
| Neutrik | 10 cifras | EAN + referencia Code39 | Caja de 10 con 10 nº de serie |
| Sound Devices | 12 caracteres Code128 | EAN-13 | Ninguno: etiqueta limpia |
| Williams AV | Code128 `BS01…` (del sistema) | UPC | Kit con un nº de serie de caja |
| Optocore | Solo impreso (`X94-2353`) | Solo impreso | Escritura manual |
| Whirlwind, LINK, conectores Neutrik | Probablemente sin nº de serie | EAN/UPC | Control por cantidad |

## Cómo están los datos en Odoo

- **Odoo 19**. No consta si es Community o Enterprise: **pregúntalo** (la app
  Código de barras de Odoo es solo Enterprise).
- Productos cargados desde Excel con `rms_product_import`:
  - Categoría = **Marca > Familia > Subfamilia**.
  - `default_code` = la columna "Referencia", quitando los prefijos de estado
    `2M-` (2ª mano) y `D-` (demo).
  - **No se importa el código de barras (EAN)**: casi ningún producto lo tiene.
  - Atributo **"Estado"** que crea **variantes** (Nuevo, Demo, 2ª Mano...) con
    la misma referencia, y atributo "2MV" (Vendible) sin variante.
- `rms_product_state`: estado por **número de serie** (`stock.lot`: Nuevo,
  Demo, Ex-Demo, 2ª Mano, Descontinuado), precio especial por número de serie,
  bloqueo de venta de demos, selección de números de serie en el pedido y
  archivado automático de descontinuados sin stock.
  **Conviven dos modelos de estado (variante y número de serie)**: es un punto
  a decidir en la entrevista (cuál manda y si sobra el otro).

## Módulos de almacén que ya existen en el repositorio

| Módulo | Qué hace |
|---|---|
| `rms_stock_barcode_scan` | Escaneo con cámara o PDA (modo teclado) de nº de serie para un producto elegido: suma a Inventario físico o rellena líneas de recepción/entrega desde el albarán |
| `rms_stock_lot_label_print` | Etiqueta 10×5 cm con referencia + nº de serie en Code128; **etiqueta sustituta** (nº de serie grabado, etiqueta dañada, caja con varios equipos) con estado y motivo |
| `rms_stock_count_session` | **Recuento cruzado** con varios operarios: escaneo libre, lecturas guardadas al momento con cola sin conexión, informe de cruce (coincide / solo una parte / cantidades distintas / nuevo / nadie lo vio), volcado a Inventario físico sin aplicar. Reglas de lectura por marca y códigos alternativos de producto |
| `rms_product_state` | Estados por número de serie y reglas de venta (ver arriba) |
| `stock_cession` | Cesiones: saca mercancía a una ubicación de cliente o virtual manteniendo la trazabilidad |
| `rms_customer_equipment_map`, `rms_global_equipment_map`, `rms_partner_equipment_model_import` | Mapa de equipos instalados en clientes |

Antes de proponer un desarrollo, revisa el código de estos módulos: puede que
ya cubra el requisito o que baste con ampliarlo.

## Hardware: decisiones y recomendaciones previas

- PDA: Android 13 o superior con servicios de Google, lector 2D (imager), modo
  teclado con sufijo Enter, IP65. Gama económica: Newland, Urovo, Chainway;
  profesional: Zebra TC22/TC27, Honeywell CT30 XP. Alternativa: lector
  Bluetooth con un móvil. Se usa Odoo desde Chrome, sin app especial.
- **La impresora UNYKA UK56009 que tienen no sirve** para etiquetas: es de
  tickets (80 mm, ESC/POS, térmica directa). Recomendada una impresora de
  etiquetas de 4" de transferencia térmica (Zebra ZD421t o similar) con
  etiquetas de 100×50 mm. Hoy la etiqueta sale en PDF y se imprime desde el
  navegador; imprimir directo en ZPL por red es una ampliación posible.
- No consta la cobertura Wi‑Fi del almacén.

## Preguntas que siguen abiertas

- Odoo Community o Enterprise.
- Qué significan las pegatinas verdes y cómo se marcan hoy las demos.
- Cómo están hoy las ubicaciones (¿existen en Odoo?, ¿rotuladas?).
- Cómo se gestionan los kits (Sony UWP-D, Williams AV): un producto o varios.
- Si el alquiler propio (rental) pasa por este almacén y cómo.
- Volúmenes: referencias activas, unidades, movimientos al día, personas.
