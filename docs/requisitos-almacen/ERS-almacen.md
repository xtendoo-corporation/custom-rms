# ERS · Sistema de almacén e inventario · RMS Proaudio

Versión: 0.4 · Fecha: 2026-11-03 · Estado: borrador
Participantes: administrador de la empresa; segundo participante de los audios
del 27-10-2026 (pendiente de confirmar quién es).

## 1. Objetivos y alcance

- **Problema mayor**: tener la **trazabilidad completa de cada equipo por su
  número de serie** a lo largo de toda su vida y en todos sus estados (nuevo,
  demo, ex-demo, segunda mano), con sus salidas que vuelven (depósitos,
  sustituciones, reparaciones). Pasar de Sage y Excel a Odoo sin perder
  información.
- Se resuelve **por partes**, en este orden propuesto (ver `entrevista.md`):
  1. identidad y estado del equipo;
  2. depósitos de demo y equipos de sustitución;
  3. reservas;
  4. segunda mano;
  5. servicio técnico;
  6. paquetes de segunda mano.
- Objetivos medibles: _pendiente_.

## 2. Situación actual (AS-IS)

Resumen de los audios del 27-10-2026; el detalle está en `entrevista.md`.

| Flujo | Cómo se hace hoy | Problema |
|---|---|---|
| Compra de nuevo | Pedido en Sage, EXW, recepción punteando el packing list y detallando números de serie | Solo el pedido está en Sage |
| Venta | Presupuesto → pedido → albarán | Reservas de Sage desactivadas por conflictos |
| Estados | 4 "almacenes"; la referencia cambia con el estado | Se pierde la historia del número de serie |
| Demo | Depósito (antes albarán serie B), vuelve como demo y rota; pasa a ex-demo | Sin control de qué está fuera ni hasta cuándo |
| Segunda mano | Pedido de compra al cliente | No se liga a la venta del intercambio; costes de reacondicionado fuera del coste |
| Paquetes 2ª mano | Excel | Sin reservas; varios comerciales venden lo mismo |
| Servicio técnico | Ficha en Excel impresa; piezas en el albarán; Excel de RA | Componentes sin trazabilidad; equipos de sustitución sin registrar |

## 3. Volúmenes y restricciones

| Dato | Valor | Fuente |
|---|---|---|
| Edición de Odoo | Community (sin app Código de barras) | Administrador, 2026-11-03 |
| Sistema actual | Sage (Odoo no está en marcha en almacén) | Administrador, 2026-11-03 |
| **Arranque de Odoo en almacén** | **1 de enero de 2027** | Administrador, 2026-11-03 |
| Zonas por estado | 4 zonas separadas físicamente; se admiten mezclas temporales | Administrador, 2026-11-03 |
| Quién cambia el estado | Administración (por ahora) | Administrador, 2026-11-03 |
| Stock Meyer en Sage | rms 5.074 u. / 456 art.; espacio 1.298 u. / 212 art.; rjb 138 u. / 26 art. | Exportaciones de Sage, 2026-11-03 |
| Empresas | **3 empresas distintas**, con 7 almacenes cada una. Códigos en Sage: 01 = RMS, 02 = Espacio Tecnológico, 03 = RJB | Administrador, 2026-11-03; sesión del panel BI |
| Números de serie en Sage | El informe "Valoración de stocks" no los trae. El informe "Situación de stock" sí, con lotes: en Point Source, 229 números de serie reales y 165 unidades con "S/N" genérico | Exportaciones de Sage |
| Posible paso a Enterprise | En estudio, por la contabilidad | Administrador, 2026-11-03 |

**Community frente a Enterprise.** Enterprise es Community más módulos de pago
sobre la misma base de datos, así que pasar de uno a otro en la misma versión
(19) no obliga a migrar los datos del inventario. Los módulos propios basados
en el estándar (`stock.lot`, `stock.picking`, `stock.location`) siguen
funcionando; hay que probarlos tras el cambio. Dos condiciones:
- El alojamiento debe admitir módulos propios: Odoo.sh o servidor propio. En
  Odoo Online (SaaS) no se pueden instalar.
- Lo único que se solaparía es el escaneo de recepciones y salidas: Enterprise
  trae la app Código de barras. Esa parte conviene decidirla después de saber
  la edición.
Las partes 1 (estado e historial), 2 (depósitos) y 3 (reservas, estándar), y
la carga de datos, valen igual en las dos ediciones.
| Último nº de pedido de compra | ≈ 4386 | Audio Mov_almacen |
| Marcas con soporte técnico | ~24 (repuestos sobre todo de Meyer, DiGiCo y Point Source) | Audio 32 |
| Resto | _pendiente_ | |

## 4. Modelo propuesto (TO-BE)

_Pendiente de completar con la entrevista._

Decisiones tomadas:
- **La referencia del producto no cambia con el estado** (audios). El estado es
  un dato del número de serie, con su historial.
- **El estado no depende de la ubicación.** Hay una zona por estado (Nuevo,
  Demo, Ex-demo, 2ª mano), pero un equipo puede estar temporalmente en otra
  zona. Odoo debe mostrar esas discrepancias sin bloquearlas.
- **Cambio de estado programado o manual**, decidido por administración.

## 5. Requisitos (borrador, sacados de los audios)

Prioridades y criterios de aceptación provisionales hasta validarlos en la
entrevista.

### 5.1 Funcionales

| ID | Requisito | Prioridad | Cobertura | Origen |
|---|---|---|---|---|
| RF-01 | Un equipo se identifica por producto + número de serie; la referencia del producto no cambia al cambiar de estado. **Decidido: una referencia por producto, sin variantes "Estado"** | Must | Ya existe en parte (`rms_product_state`); hay que quitar las variantes "Estado" de `rms_product_import` y unificar los productos (M) | Audio Demo_exdeml; administrador, 2026-11-03 |
| RF-02 | Historial por número de serie: entradas, salidas, clientes, cambios de estado con fecha y usuario | Must | Estándar Odoo para los movimientos (trazabilidad del lote); **Desarrollo** para el historial de estado (M) | Audio Demo_exdeml |
| RF-03 | Cambio de estado Nuevo → Demo → Ex-demo → 2ª mano como operación registrada, no como edición libre | Must | Desarrollo (S/M) | Audio Demo_exdeml |
| RF-03a | Programar el cambio de estado: estado destino y fecha en el número de serie; llegada la fecha, el cambio se aplica solo. Sin fecha, el cambio es manual | Must | Desarrollo (S): tarea programada sobre `rms_product_state` | Administrador, 2026-11-03 |
| RF-03d | Al cambiar el estado (programado o manual) se avisa a los comerciales (p. ej. "nuevo ex-demo a la venta"). Sin tarea de traslado físico | Must | Desarrollo (S): actividad o mensaje | Administrador, 2026-11-03 |
| RF-03e | Precio de ex-demo y segunda mano fijado equipo a equipo en el número de serie | Must | Ya existe (`custom_price` en `rms_product_state`); a verificar en la venta | Administrador, 2026-11-03 |
| RF-03b | Solo administración puede cambiar o programar el estado | Must | Desarrollo (S): grupo de permisos | Administrador, 2026-11-03 |
| RF-03c | Informe de equipos fuera de la zona de su estado (p. ej. una demo en la zona de nuevo) | Should | Desarrollo (S) o filtro sobre el stock | Administrador, 2026-11-03 |
| RF-04 | Demo no vendible, ex-demo vendible con su precio | Must | Ya existe (`rms_product_state`: bloqueo de venta de demo y precio por número de serie). A verificar | Audio Demo_exdeml |
| RF-05 | Depósito: salida de equipos con número de serie a un cliente, que vuelve, con fecha prevista de devolución y avisos | Must | Ampliación de `stock_cession` (M) | Audios Demo_exdeml y 32 |
| RF-06 | Equipo de sustitución durante una reparación, ligado a la reparación y con devolución controlada | Should | Desarrollo, sobre RF-05 (S/M) | Audio 32 |
| RF-07 | Reservas por cantidad en pedidos de venta; asignación de lo recibido por orden de pedido | Must | Estándar Odoo (reservas en albaranes) a configurar y validar | Audios Mov_almacen_v2 y 28 |
| RF-08 | Compra para un pedido de venta concreto: al recibir, queda reservada para ese pedido | Should | Estándar Odoo (ruta "bajo pedido" / MTO) a validar | Audio Mov_almacen_v2 |
| RF-09 | Guardar el número de pedido de la fábrica en el pedido de compra | Must | Estándar Odoo (referencia del proveedor) | Audio Mov_almacen |
| RF-10 | Compra de segunda mano ligada a la oportunidad o venta del intercambio | Should | Desarrollo (S) o estándar (origen / CRM) a validar | Audio 2_mano |
| RF-11 | Costes de reacondicionado imputados al coste de las unidades de segunda mano | Should | A estudiar: costes en destino (`stock_landed_costs`, Community) o desarrollo | Audio 29 |
| RF-12 | Segunda mano "no vendible" fuera del valor de stock que se reporta | Should | A estudiar (atributo 2MV o estado) | Audio 31 |
| RF-13 | Bloquear N unidades de segunda mano para un cliente mientras se negocia | Must | A estudiar (reserva o presupuesto con números de serie) | Audio Paquetes de 2a Mano |
| RF-14 | Paquetes combinables de segunda mano con precio por unidad | Could | Desarrollo (L) | Audios 30 y Paquetes de 2a Mano |
| RF-15 | Fichas de reparación (garantía / fuera de garantía, presupuesto) | Should | Estándar `repair` (Community) a validar | Audio 32 |
| RF-16 | Ubicación RA y circuito de devolución de piezas a fábrica | Should | Estándar (ubicación + traslados) y Proceso | Audio 32 |
| RF-17 | Componentes con número de serie montados en un equipo (qué etapa lleva cada caja) | Could | Desarrollo (M/L) | Audios 31 y 32 |

### 5.2 No funcionales

| ID | Requisito | Origen |
|---|---|---|
| RNF-01 | La parte 1 (identidad, estado e historial) y la carga de datos deben estar listas y probadas antes del **1 de enero de 2027** | Administrador, 2026-11-03 |

### 5.3 Datos

| ID | Requisito | Cobertura |
|---|---|---|
| RD-01 | Migración desde Sage: productos con referencia única (sin una referencia por estado), números de serie con su estado actual y stock por ubicación. **Fecha límite: 1 de enero de 2027** | Desarrollo / carga (a dimensionar) |
| RD-02 | **Recuento físico antes del arranque para validar y completar los números de serie.** Se parte de los que exporta Sage ("Situación de stock"), que están incompletos (lotes "S/N") y tienen incoherencias. Se propone el recuento cruzado (`rms_stock_count_session`), con lo de Sage como stock esperado | Ya existe + Proceso |
| RD-06 | Carga de números de serie desde el informe "Situación de stock" de Sage, con informe de incidencias: lotes "S/N", sumas que no cuadran con el stock, números de serie repetidos en varios productos | Desarrollo / carga (M) |
| RD-07 | Tres empresas en Odoo, cada una con sus almacenes (correspondencia pendiente) | Estándar Odoo (multicompañía) a configurar |
| RD-03 | Unificar las referencias de Sage que codifican el estado (`2M-`, `D-`, `-DEMO`, `DEMO-`, `D` sin guion) en una sola referencia, pasando el estado al número de serie | Desarrollo / carga (M) |
| RD-04 | Repuestos por cantidad (tornillos, tuercas, mangos...) como productos sin número de serie en su propia ubicación | Carga + Estándar Odoo |
| RD-05 | Correspondencia de los almacenes de Sage (AL1, AL2, A.4...) con ubicaciones de Odoo | Pendiente de saber qué es cada uno |

## 6. Análisis de brechas

_Pendiente: se completará al cerrar cada parte._

## 7. Plan por fases

_Pendiente._

## 10. Supuestos y preguntas abiertas

- [x] Paso de Sage a Odoo: almacén sigue en Sage; arranque el 1 de enero de 2027.
- [x] Zonas por estado: separadas, con mezclas temporales permitidas.
- [x] Cambio de estado: administración; con fecha programada o manual.
- [x] Listado de Sage: existe por artículo y almacén, sin números de serie.
- [x] Una referencia por producto; precio de ex-demo y 2ª mano equipo a equipo.
- [x] Al llegar la fecha: cambia el estado y se avisa a comerciales (a + c).
- [x] RMS, Espacio y RJB son tres empresas distintas, con 7 almacenes cada una.
- [ ] ¿Se puede sacar "Situación de stock" con lotes para todas las marcas y empresas?
- [ ] ¿Qué es cada almacén de Sage (AL1, AL2, A.4, A.6, A.7, A.9, AL5, AL7, AL8, AL9, ALB, STM, STS)?
- [ ] ¿Cómo se identifica hoy un ex-demo en Sage?
- [ ] Decisión Community / Enterprise y tipo de alojamiento.
- [ ] Qué se guarda de los pactos de demo con la fábrica (precio, plazo sin vender).
- [ ] ¿El atributo "2MV" es la "segunda mano vendible"?
- [ ] ¿Quién es el segundo participante de los audios?
