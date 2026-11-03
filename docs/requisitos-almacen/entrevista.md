# Registro de la entrevista · Almacén e inventario

Skill `/experto-almacen`. Registro breve de preguntas, respuestas y decisiones.
Las correcciones que aparecen aquí mandan sobre
`.claude/skills/experto-almacen/references/contexto-rms.md`.

## 2026-11-03 · Sesión 1

**Responde:** el administrador de la empresa (usuario de Claude). Odoo
**Community**. Problema principal: "otro" (se explica en los audios).

### Fuente: 10 audios de una reunión del 27-10-2026 (con permiso de los participantes)

Transcritos automáticamente (Whisper). Participan el administrador y otra
persona de la empresa que conoce la operativa. Pendiente de confirmar quién es:
en un audio se cita a "Miguel Ángel Jiménez como CEO".

| Audio | Tema |
|---|---|
| Mov_almacen | Compra de producto nuevo a fábrica y recepción |
| Mov_almacen_v2 | Stock, reservas y ventas |
| Nueva grabación 28 | Resumen compras / ventas; reservas en Sage desactivadas |
| Demo_exdeml | Ciclo Nuevo → Demo → Ex-demo; depósitos; trazabilidad por número de serie |
| 2_mano | Compra de segunda mano a clientes (intercambio por equipo nuevo) |
| Nueva grabación 29 | Costes de reacondicionado de la segunda mano |
| Nueva grabación 30 | Venta de segunda mano por paquetes combinables |
| Paquetes de 2a Mano | Paquetes: qué se hace hoy y qué es prioritario |
| Nueva grabación 31 | Segunda mano "vendible"; componentes con número de serie |
| Nueva grabación 32 | Servicio técnico, garantías, almacén RA, equipo de sustitución |

### Lo que se entiende de los audios (situación actual)

**Sistema actual: Sage.** Odoo es el sistema al que se quiere pasar.

1. **Compra de nuevo**
   - Pedido de compra a fábrica (numeración propia; van por el 4386). La fábrica
     confirma con su "sales order" y una fecha. Se anota el número de pedido de
     la fábrica para casar después su factura.
   - Incoterm EXW: un transportista propio recoge en fábrica y lo trae (avión,
     aduanas, DUA y aranceles).
   - En la nave se descarga, se puntea contra el packing list o la factura, y se
     recibe en el pedido detallando los números de serie. En Sage solo sale el
     pedido de compra; el resto de la gestión es externa.
2. **Ventas y reservas**
   - Presupuesto (CRM) → pedido de venta aprobado → albarán de salida.
   - Si no hay stock, el pedido espera a que llegue la compra.
   - Se quiere poder comprar para un pedido concreto y que, al llegar, el
     sistema diga "esto es para este pedido".
   - Si varios pedidos esperan la misma mercancía, se sirve **por orden de
     pedido**.
   - En producto nuevo al comercial le da igual el número de serie: reserva
     cantidad.
   - Sage tiene reservas, pero están **desactivadas por conflictos**.
3. **Estados del equipo: Nuevo, Demo, Ex-demo, Segunda mano**
   - En Sage son cuatro "almacenes" y **cambia la referencia del producto**
     según el estado. **En Odoo no se quiere que cambie la referencia.**
   - Un equipo puede pasar por todos los estados.
   - Se quiere la **trazabilidad completa por número de serie**: entró de
     fábrica, pasó a demo en tal fecha, estuvo con tal cliente, se vendió, se
     recompró, se volvió a vender.
4. **Demo**
   - Hay pactos con fábricas: precio especial para demo a cambio de no
     venderlo durante un tiempo.
   - Un equipo recibido como nuevo se decide pasar a demo.
   - Sale con un **depósito** (antes, albarán de serie B "que vuelve"; serie A
     = se factura). El cliente lo prueba y lo devuelve; vuelve como demo y rota
     a otros clientes.
   - Cuando ya no se quiere usar como demo pasa a **ex-demo**, con precio
     concreto. **Demo no es vendible; ex-demo sí.**
5. **Segunda mano**
   - Se compra a un cliente con un pedido de compra, como a fábrica. Suele ser
     parte de una operación de intercambio (p. ej. 12 Leopard recompradas al
     vender Tigra).
   - Debe quedar registrado que la compra viene de esa operación de venta. Hoy
     van por caminos separados y nada lo liga.
   - **Costes de reacondicionado** (limpieza, pintura, chequeo, reparaciones)
     del servicio técnico: deben sumarse al coste de esas unidades (12 × 1.000 €
     + 1.000 € de reacondicionado = 13.000 €).
   - Se distingue **segunda mano vendible** de la que no se venderá nunca: la
     segunda no debe contar en el valor de stock que se reporta.
6. **Paquetes de segunda mano** (no prioritario)
   - Se vende en paquetes (mínimo 4 cajas, accesorios como patines o top grid
     a 0 €), con precio por unidad según su estado.
   - Se querría combinar unidades libremente y reservar las de un paquete
     ofrecido. Hoy se hace en Excel.
   - **Prioridad declarada**: saber qué hay y bloquear N unidades cuando un
     cliente las pide. Varios comerciales ofrecen el mismo stock y el primero
     que vende se lo queda.
7. **Servicio técnico**
   - Se recibe el equipo del cliente, se abre una ficha en Excel y se imprime.
   - En garantía se repara y se devuelve. Fuera de garantía: presupuesto,
     aprobación del cliente, pago y envío.
   - En los albaranes se apunta qué componente sale y cuál entra.
   - Componentes con número de serie (etapas, conos) dentro de un altavoz con
     número de serie. Se quiere saber qué etapa lleva cada caja.
   - **Almacén RA**: piezas en garantía para devolver a fábrica, controladas
     con un Excel de RA. Intercambio: al cliente se le pone una etapa de
     repuesto propia, la rota va a fábrica y la fábrica repone otra.
   - Repuestos propios: sobre todo Meyer, DiGiCo y Point Source. Atlas suele
     mandar la caja entera.
   - Mientras se repara, se deja al cliente **un equipo de demo de
     sustitución**. No queda registrado y a veces no se devuelve.

### Contraste con lo que ya hay en Odoo (revisión del código)

- `rms_product_state` ya pone el **estado en el número de serie** (Nuevo, Demo,
  Ex-Demo, 2ª Mano, Descontinuado), con precio por número de serie y bloqueo de
  venta de demos. **No guarda historial** de cambios de estado.
- `rms_product_import` crea **variantes por "Estado"** con la misma referencia.
  Choca con "no queremos que cambie la referencia": hay que decidir.
- `stock_cession` hace cesiones: un producto y una cantidad por documento,
  **sin número de serie, sin fecha de devolución y sin circuito de vuelta**.
  Es la base natural del "depósito", pero se queda corta.
- Atributo "2MV" (Vendible) de `rms_product_import`: probablemente es la
  "segunda mano vendible". A confirmar.

### Propuesta de orden (problema mayor dividido en partes)

1. Identidad y estado del equipo: un producto con su número de serie, estado e
   historial (base de todo lo demás).
2. Depósitos de demo y equipos de sustitución (salidas que vuelven).
3. Reservas en ventas y compras para un pedido concreto.
4. Segunda mano: compra ligada al intercambio, costes de reacondicionado,
   vendible o no.
5. Servicio técnico: fichas de reparación, RA, componentes.
6. Paquetes de segunda mano (no prioritario).

### Preguntas y respuestas de la sesión 1

1. **¿En qué punto está el paso de Sage a Odoo?**
   Se sigue con Sage. Odoo no está en marcha en almacén. **Arranque previsto:
   1 de enero (2027).**
2. **¿Están separados físicamente los cuatro estados?**
   Sí, en zonas separadas, pero **no es cerrado**: una zona puede tener
   temporalmente equipos de otro estado.
3. **¿Quién decide el cambio de estado y cuándo?**
   Decide **administración** (por ahora). Se quiere poder poner **una fecha
   para que el equipo pase a otro estado**; si no hay fecha, el cambio se hace
   a mano.

**Decisiones que se derivan:**
- El estado es un dato del número de serie, no de la ubicación. La zona dice
  dónde está; un equipo en una zona que no es la de su estado se permite, pero
  debe poder verse.
- El arranque del 1 de enero convierte la carga de datos desde Sage (números
  de serie con su estado y ubicación) en el requisito más urgente.

### Preguntas y respuestas de la sesión 1, segunda tanda

1. **¿Se puede sacar de Sage un listado por número de serie?**
   Se entregan tres exportaciones de Sage "Valoración de stocks" de Meyer:
   `stock_meyer_rms.xlsx`, `stock_meyer_espacio.xlsx` y `stock_meyer_rjb.xlsx`
   (análisis abajo). **No llevan número de serie.**
2. **¿Una sola referencia por producto?**
   **Sí**, una referencia por producto (se quitan las variantes "Estado"). El
   precio de ex-demo y segunda mano se pone **equipo a equipo**.
3. **¿Qué más pasa al llegar la fecha de cambio de estado?**
   **a + c**: cambia el estado y se avisa a los comerciales. Sin tarea de
   traslado físico.

**Duda planteada:** se habla de pasar de Community a **Enterprise** por la
contabilidad. ¿Conviene avanzar con el inventario? Ver la respuesta en el chat
y en la ERS, sección 3.

### Análisis de las exportaciones de Sage (Meyer)

Formato: almacén, artículo, nombre y unidades. Cuando un artículo está en
varios almacenes, las líneas siguientes vienen sin artículo.

| Fichero | Líneas | Artículos | Unidades | Nuevo | Demo | 2ª mano |
|---|---|---|---|---|---|---|
| rms | 598 | 456 | 5.074 | 4.603 | 57 | 414 |
| espacio | 290 | 212 | 1.298 | 861 | 205 | 232 |
| rjb | 26 | 26 | 138 | 36 | 0 | 102 |

- **No hay números de serie.** La carga en Odoo no puede sacarlos de Sage: hay
  que capturarlos en un recuento físico antes del arranque.
- **El estado va codificado en la referencia, de forma irregular**: `2M-…`,
  `D-…`, `…-DEMO`, `DEMO-…`, `D4024906101` (sin guion). **No aparece ninguna
  referencia de ex-demo.**
- **Los almacenes de Sage no son los estados.** `AL1` mezcla nuevo, demo y
  segunda mano. Códigos: AL1, AL2, AL5, AL7, AL8, AL9, ALB, A.4, A.6, A.7, A.9,
  STM y STS.
- **Hay repuestos por cantidad** (tornillos, tuercas, mangos; referencias de 6
  cifras como `101567`), sobre todo en AL2 y A.4.
- Los artículos de Meyer son su número de pieza sin puntos: `0923700102` es el
  `09.237.001.02` impreso en la caja. Con la comparación sin puntos que ya hace
  el escáner, la etiqueta de la caja identifica el producto.
- Los tres ficheros comparten artículos: 63 entre rms y espacio, 13 entre rms
  y rjb.

### Preguntas y respuestas de la sesión 1, tercera tanda

1. **¿Qué son RMS, Espacio y RJB?**
   **Tres empresas distintas.** Cada una tiene 7 almacenes. (El administrador
   indica que ya se habló en conversaciones anteriores: se está buscando en
   sus otras sesiones.)
2. **¿Qué es cada código de almacén de Sage?**
   Pendiente: se recupera de las conversaciones anteriores. Dato seguro: `AL1`
   = "Almacen Delegacion de Madrid" (informe de Point Source).
3. **¿Cómo se identifica un ex-demo en Sage?**
   El administrador no lo sabe; lo pregunta y lo comunica.

### Análisis del informe de Sage "Situación de stock" (Point Source)

`POINT_SOURCE.xlsx`: informe distinto al de Meyer, con columnas de stock,
virtual, disponible, pedido de venta, pedido de compra, mínimo y máximo, y
**una línea por lote o número de serie** debajo de cada almacén.

- 578 artículos, 80 con stock; 503 unidades, todas en AL1. 2 unidades en
  pedidos de venta y 84 en pedidos de compra.
- **229 números de serie reales**, todos con cantidad 1. Casi todos tienen 7
  cifras (`2524001`, `2410326`…).
- **165 unidades con el lote genérico "S/N"**: equipos o accesorios sin número
  de serie apuntado.
- De los artículos con stock: 25 con números de serie reales, 38 solo con
  "S/N" y 17 sin lotes (material por cantidad).
- **Problemas de calidad de datos:**
  - 4 artículos cuyos números de serie no suman su stock
    (`PS-CO-8WD-XSK-BE`: stock 14 y 35 números de serie;
    `D-PS-CO-8WD-XSK-BE`: stock 1 y 2 números de serie).
  - 2 números de serie repetidos en dos productos distintos
    (`2303008`, `2634023`).
- Conclusión: Sage **sí** puede exportar números de serie, pero incompletos y
  con incoherencias. Se pueden usar como **punto de partida** del recuento del
  arranque, no como dato definitivo.

### Preguntas pendientes

1. ¿Se puede sacar este mismo informe "Situación de stock" (con lotes) para
   todas las marcas y las tres empresas?
2. Ex-demo en Sage (pendiente de respuesta del administrador).
