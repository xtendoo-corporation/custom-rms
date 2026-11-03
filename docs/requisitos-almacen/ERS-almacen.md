# ERS · Sistema de almacén e inventario · RMS Proaudio

Versión: 0.1 · Fecha: 2026-11-03 · Estado: borrador
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
| Último nº de pedido de compra | ≈ 4386 | Audio Mov_almacen |
| Marcas con soporte técnico | ~24 (repuestos sobre todo de Meyer, DiGiCo y Point Source) | Audio 32 |
| Resto | _pendiente_ | |

## 4. Modelo propuesto (TO-BE)

_Pendiente de completar con la entrevista._

Principio ya acordado en los audios: **la referencia del producto no cambia
con el estado**. El estado es un dato del número de serie, con su historial.

## 5. Requisitos (borrador, sacados de los audios)

Prioridades y criterios de aceptación provisionales hasta validarlos en la
entrevista.

### 5.1 Funcionales

| ID | Requisito | Prioridad | Cobertura | Origen |
|---|---|---|---|---|
| RF-01 | Un equipo se identifica por producto + número de serie; la referencia del producto no cambia al cambiar de estado | Must | Ya existe en parte (`rms_product_state`); hay que decidir qué pasa con las variantes "Estado" de `rms_product_import` | Audio Demo_exdeml |
| RF-02 | Historial por número de serie: entradas, salidas, clientes, cambios de estado con fecha y usuario | Must | Estándar Odoo para los movimientos (trazabilidad del lote); **Desarrollo** para el historial de estado (M) | Audio Demo_exdeml |
| RF-03 | Cambio de estado Nuevo → Demo → Ex-demo → 2ª mano como operación registrada, no como edición libre | Must | Desarrollo (S/M) | Audio Demo_exdeml |
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

_Pendiente._

### 5.3 Datos

| ID | Requisito | Cobertura |
|---|---|---|
| RD-01 | Migración desde Sage: productos con referencia única (sin una referencia por estado), números de serie con su estado actual y stock por ubicación | Desarrollo / carga (a dimensionar) |

## 6. Análisis de brechas

_Pendiente: se completará al cerrar cada parte._

## 7. Plan por fases

_Pendiente._

## 10. Supuestos y preguntas abiertas

- [ ] Estado del paso de Sage a Odoo (qué módulos están ya en uso).
- [ ] ¿Los cuatro estados están separados físicamente en la nave?
- [ ] Quién cambia el estado y cuándo; qué se guarda de los pactos de demo.
- [ ] ¿El atributo "2MV" es la "segunda mano vendible"?
- [ ] ¿Quién es el segundo participante de los audios?
