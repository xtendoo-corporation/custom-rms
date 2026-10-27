# Plantilla de la Especificación de Requisitos (ERS) del almacén

Formato de `docs/requisitos-almacen/ERS-almacen.md`. Rellena solo lo que se
haya hablado; lo pendiente va como supuesto o pregunta abierta, no inventado.

```markdown
# ERS · Sistema de almacén e inventario · RMS Proaudio

Versión: 0.x · Fecha: AAAA-MM-DD · Estado: borrador | en revisión | aprobada
Participantes: <nombre y rol de quien responde>

## 1. Objetivos y alcance
- Problema que se resuelve y objetivo medible (p. ej. IRA > 97 % general y > 99 % en números de serie en 6 meses,
  recuento completo en menos de 2 días).
- Dentro del alcance / fuera del alcance.

## 2. Situación actual (AS-IS)
Por flujo: recepción, almacenaje, salidas, demos y cesiones, reparación,
inventario. Qué se hace, quién, con qué herramienta y qué falla.

## 3. Volúmenes y restricciones
| Dato | Valor | Fuente |
|---|---|---|
| Referencias activas | | |
| Unidades con nº de serie | | |
| Recepciones / semana | | |
| Salidas / día | | |
| Ubicaciones | | |
| Operarios | | |
Edición de Odoo (Community/Enterprise), presupuesto, plazos.

## 4. Modelo de almacén propuesto (TO-BE)
Zonas y codificación de ubicaciones, estados, etiquetas, hardware, flujo
objetivo de cada proceso (puede incluir un diagrama en Mermaid).

## 5. Requisitos

### 5.1 Funcionales
| ID | Requisito | Prioridad | Cobertura | Origen |
|---|---|---|---|---|
| RF-01 | ... | Must | Estándar Odoo: <ajuste/menú> | Entrevista, bloque 5 |

Para cada RF relevante:

**RF-01 · <título>**
- Descripción: ...
- Criterios de aceptación:
  - Dado <contexto>, cuando <acción>, entonces <resultado verificable>.
- Cobertura: Estándar Odoo | Ya existe (<módulo>) | Desarrollo (<módulo>, S/M/L) | Proceso
- Notas / dependencias:

### 5.2 No funcionales (RNF-xx)
Rendimiento (p. ej. respuesta de un escaneo en menos de 1 s con Wi‑Fi),
funcionamiento con cortes de red, permisos, auditoría, usabilidad en PDA.

### 5.3 Datos (RD-xx)
Limpieza y carga: EAN, referencias, seguimiento, estados, ubicaciones,
números de serie existentes, stock inicial.

## 6. Análisis de brechas
| Área | Estándar Odoo | Ya existe en rms_* | Desarrollo | Proceso |
|---|---|---|---|---|

## 7. Plan por fases
| Fase | Contenido (RF/RD) | Requisito previo | Estimación |
|---|---|---|---|

## 8. Hardware
| Equipo | Modelo propuesto | Cantidad | Uso |
|---|---|---|---|

## 9. Riesgos
| Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|

## 10. Supuestos y preguntas abiertas
- [ ] ...

## 11. Glosario
IRA, ABC, putaway, SSCC, recuento ciego, etiqueta sustituta...
```

Escala de estimación orientativa para desarrollo: **S** hasta 2 días, **M**
de 3 a 8 días, **L** más de 8 días (a refinar por el desarrollador).
