# Ingeniería de almacén: buenas prácticas y cómo se resuelven en Odoo 19

Chuleta del experto. Úsala para proponer soluciones con fundamento y para
decir en cada requisito si es estándar de Odoo, si ya existe en el
repositorio o si hay que desarrollarlo. Los nombres técnicos de Odoo de este
fichero se comprobaron contra el código fuente de Odoo 19 (rama 19.0,
octubre de 2026); ese código no está en este repositorio.

## 1. Principios que casi siempre aplican

1. **Primero datos y ubicaciones, después automatización.** Sin productos
   bien definidos (seguimiento, referencias, códigos) y sin ubicaciones
   rotuladas, ninguna PDA arregla el inventario.
2. **Un código de barras, un significado.** Cada etiqueta propia identifica
   una sola cosa: ubicación, producto, número de serie o bulto. Nunca dos
   códigos en la misma etiqueta sin decir cuál es cuál.
3. **Escanear para confirmar, no para teclear.** Cada movimiento físico
   relevante se confirma escaneando: la ubicación de origen o destino y el
   producto o número de serie.
4. **El sistema manda.** Si algo se mueve sin registrarse en Odoo, el
   inventario se degrada. Cualquier "excepción" (demo urgente, préstamo a un
   amigo de la casa) necesita un circuito igual de rápido que saltárselo.
5. **Medir la exactitud (IRA).** IRA = líneas producto-ubicación contadas
   sin diferencia ÷ líneas contadas (para números de serie: números de serie
   en su ubicación correcta ÷ contados). Objetivo razonable: más del 97 % en
   general y más del 99 % en equipos con número de serie de alto valor.
6. **Separar físicamente los estados** (nuevo, demo, 2ª mano, reparación,
   cuarentena): mejor una zona o ubicación por estado que una marca a
   rotulador en la caja.

## 2. Ubicaciones

- **Codificación recomendada**: `ZONA-PASILLO-MÓDULO-NIVEL-HUECO`, con ancho
  fijo y legible en voz alta, p. ej. `A-01-03-2` (zona A, pasillo 01,
  módulo 03, nivel 2). Rótulo con código de barras Code128 en cada hueco y
  en la cabecera del pasillo.
- **Zonas típicas en un distribuidor de audio**: recepción (muelle), control
  o pendiente de verificar, stock nuevo, demo, ex-demo/2ª mano, reparación y
  RMA, cuarentena, salida/expedición, cesiones (ubicación virtual por
  cliente), y pequeño material en estanterías de picking.
- **Granularidad**: equipo grande por hueco o por palé; pequeño material por
  estante. No se crea una ubicación por caja: para eso están los bultos.
- **Odoo**: activar *Ubicaciones de almacenamiento*
  (`group_stock_multi_locations`), crear `stock.location` internas con su
  campo **Código de barras**. Las ubicaciones admiten **frecuencia de
  inventario cíclico** (`cyclic_inventory_frequency`, en días).

## 3. Productos, números de serie y estados

- Seguimiento: **por número de serie** para todo equipo con número de serie
  de fábrica o de valor; **sin seguimiento** para cables y accesorios; **por
  lote** solo si el fabricante lo usa (raro en audio).
- **Kits**: si se venden juntos pero cada componente tiene su número de
  serie (Sony UWP-D, Williams AV), conviene un producto por componente y el
  kit como lista de materiales tipo **kit** (módulo `mrp`, Community), o como
  bulto (paquete). Si el kit tiene un único número de serie de sistema, puede
  ser un producto con su número de serie.
- **Estado del equipo**: o variantes, o atributo del número de serie, **no
  las dos cosas**. En RMS existen ambas (variante "Estado" de
  `rms_product_import` y `product_state_id` en el número de serie de
  `rms_product_state`): hay que decidir cuál manda. Recomendación habitual:
  **el estado va en el número de serie** (un equipo concreto pasa de nuevo a
  demo sin cambiar de producto), con una ubicación por estado.
- **Códigos de producto**: rellenar el **EAN/UPC** del fabricante en
  `barcode` (escanear la caja identifica el producto) y la referencia del
  fabricante en `default_code`. Los códigos extra del fabricante van en
  *Códigos alternativos de producto* (`rms_stock_count_session`).

## 4. Etiquetas

- **Propia de número de serie** (`rms_stock_lot_label_print`): 100×50 mm,
  referencia en grande, número de serie en Code128 y en texto, estado si no
  es nuevo. Se pega **sin tapar** la etiqueta del fabricante (garantías).
- **Ubicación**: 100×50 o 100×30 mm, código de barras grande y texto legible
  a 2 m; en niveles altos, etiqueta de pasillo o colgante.
- **Bulto o flight case**: código de bulto (`stock.package`, prefijo propio)
  para mover y contar todo su contenido de una vez. Odoo 19 admite bultos
  dentro de bultos (`parent_package_id`).
- **Material**: transferencia térmica (con cinta) en etiquetas que deben durar
  años; térmica directa solo para envíos.
- **Estándares GS1**: EAN-13/UPC-A = producto; ITF-14/GTIN-14 = caja de varias
  unidades; SSCC (00) = palé o bulto de transporte (se ignora en almacén);
  GS1-128 con AI (21) = número de serie.

## 5. Flujos y su resolución en Odoo

| Flujo | Buena práctica | Odoo 19 |
|---|---|---|
| Recepción | Recibir contra pedido de compra, escanear números de serie, separar lo dañado | Recepción en 1, 2 o 3 pasos (`reception_steps`: `one_step`, `two_steps`, `three_steps` con control). Escaneo de números de serie en la línea: `rms_stock_barcode_scan` |
| Ubicación (putaway) | Regla por zona/estado/categoría; el operario confirma escaneando la ubicación | Reglas de almacenamiento (`stock.putaway.rule`) por producto o categoría, con categorías de almacenamiento (`stock.storage.category`) y capacidad |
| Picking y salida | Lista de recogida por ubicación, escanear número de serie para confirmar | Entrega en 1, 2 o 3 pasos (`delivery_steps`: `ship_only`, `pick_ship`, `pick_pack_ship`); estrategias de salida FIFO, LIFO, FEFO, ubicación más cercana, menos bultos; agrupaciones (`stock_picking_batch`) |
| Demos y préstamos | Salida a una ubicación de "fuera" por cliente, con fecha de retorno y aviso | `stock_cession` (ya existe); retorno = movimiento inverso |
| Reparación / RMA | Ubicación de reparación, seguimiento del número de serie enviado al fabricante | Módulo `repair` (Community) o traslados internos a una ubicación RMA |
| Recuento | Cíclico por zona o ABC; recuento ciego; doble recuento en alto valor | Inventario físico (`stock.quant`), *Solicitar recuento* (`stock.request.count`), frecuencia por ubicación, día anual de inventario (`annual_inventory_day`/`month` en la compañía). Recuento cruzado: `rms_stock_count_session` |
| Ajustes | Aprobación por umbral; motivo obligatorio | Aplicar desde Inventario físico (con permiso de responsable). El umbral o motivo obligatorio sería desarrollo |

## 6. Inventario: cómo plantearlo

- **Recuento cíclico** en lugar de un gran inventario anual cuando hay más de
  unos cientos de referencias: clasificación **ABC** por valor (A: cada mes;
  B: cada trimestre; C: una o dos veces al año) o por ubicación con la
  frecuencia de Odoo.
- **Ciego**: el operario no ve la cantidad esperada (el recuento cruzado de
  `rms_stock_count_session` ya funciona así).
- **Doble recuento cruzado** para alto valor: dos personas por separado y se
  revisa solo lo que no coincide.
- **Congelar movimientos** de la zona mientras se cuenta, o contar a primera
  hora antes de recepciones y salidas.
- **Analizar las diferencias por causa** (sin registrar, ubicación errónea,
  número de serie cambiado, error de recepción), no solo ajustar.

## 7. Hardware y dimensionado

- **PDA**: una por operario activo en almacén, más una de reserva. Android con
  servicios de Google, lector 2D, modo teclado con Enter. Odoo en Chrome.
- **Impresora de etiquetas**: una por puesto de recepción o etiquetado, 4",
  transferencia térmica, con red (para imprimir directo en el futuro).
- **Wi‑Fi**: cobertura medida en todo pasillo y nivel, sobre todo junto a
  estanterías metálicas.
- **App Código de barras de Odoo**: solo en **Enterprise**. En Community, el
  escaneo se cubre con los módulos `rms_*` (modo teclado y cámara).

## 8. Señales de alarma en la entrevista

- "Lo sabe X" o "lo apuntamos en un Excel": proceso fuera del sistema.
- Estados marcados a mano en la caja: falta una ubicación o un estado en Odoo.
- Equipos que salen "un momento" sin documento: falta un circuito de préstamo rápido.
- Más de un código para lo mismo, o productos duplicados por estado.
- Ajustes de inventario grandes sin análisis de causa.
