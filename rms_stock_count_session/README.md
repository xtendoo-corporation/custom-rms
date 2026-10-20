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
5. Cada operario pulsa **He terminado mi recorrido**. El responsable pulsa
   **Terminar recuento y cruzar**.

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
