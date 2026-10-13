# RMS Academia Odoo

Plan de formación interno sobre **todo lo que ofrece el Odoo de RMS-Proaudio**,
de lo más básico a lo más avanzado, con **control del progreso de cada
empleado** y conectado con el asistente de IA (`rms_ai_help_assistant`).

## Cómo encaja con la IA

| Pieza | Para qué sirve |
|---|---|
| **Academia Odoo** (este módulo) | La fuente oficial: rutas formativas → lecciones paso a paso → test. Se edita desde Odoo, sin tocar código. |
| **Asistente Odoo (IA)** (`rms_ai_help_assistant`) | El empleado pregunta en lenguaje natural ("¿cómo registro una cesión?"). La IA busca primero en la Academia (herramienta `buscar_formacion`), responde con los pasos oficiales y recomienda la lección para practicarla. |

Así la IA no inventa procedimientos: responde con lo que la empresa ha
validado, y cuando el Responsable de Formación corrige una lección, la IA
lo usa desde ese momento. Las dos piezas son independientes: la IA funciona
sin la Academia y la Academia funciona sin la IA.

## Qué ve cada persona

**Cualquier empleado** (menú **Academia Odoo**):

- **Aprender > Rutas formativas**: tarjetas por área (Primeros pasos,
  Clientes, Ventas, Inventario...) con su % de progreso. Filtro
  "Recomendadas para mí" según sus grupos.
- **Aprender > Plan de formación completo**: todas las lecciones, agrupadas
  por ruta y ordenadas Básico → Intermedio → Avanzado.
- **Aprender > Mis lecciones pendientes** y **Mi progreso**.
- En cada lección: *Qué aprenderás*, *Dónde se hace* (ruta de menú),
  *Paso a paso* (con el resultado esperado de cada paso), *Consejos y
  errores frecuentes*, y los botones **Empezar lección**, **Marcar como
  completada** o **Hacer el test** (si la lección tiene test, solo se
  completa aprobándolo; nota mínima configurable, 70% por defecto).

**Responsable de Formación** (grupo *Responsable de Formación (Academia
Odoo)*, incluido automáticamente en los Administradores):

- Crea y edita rutas, lecciones, pasos y preguntas de test.
- **Academia Odoo > Control de formación**: tabla dinámica empleado × ruta
  con las lecciones completadas, gráfico por nivel y listado con notas,
  intentos y fechas. Filtros por empleado, ruta, nivel o "completadas este
  mes".

Cada empleado solo ve su propio progreso (regla de registro); el responsable
ve el de todos. Un empleado no puede crear ni modificar registros de
progreso directamente: solo se generan desde los botones de la lección y del
test.

## Contenido incluido

`data/training_content_data.xml` trae un plan inicial redactado a partir del
código de los módulos de este repositorio (menús, botones y comportamientos
reales). Se carga con `noupdate="1"`: lo que el Responsable de Formación
cambie desde Odoo **no se pisa** al actualizar el módulo.

Revisadlo con quien mejor conozca cada proceso: el código explica qué hace
Odoo, pero no los procedimientos que la empresa sigue "de palabra".

## Instalación

1. Copiad `rms_training_academy` (y la versión actualizada de
   `rms_ai_help_assistant`) al `addons-path`.
2. Actualizad la lista de aplicaciones e instalad **RMS Academia Odoo**.
3. Actualizad **RMS AI Help Assistant** para que la IA reciba la nueva
   herramienta `buscar_formacion`.
4. Añadid a quien vaya a mantener la formación al grupo **Responsable de
   Formación (Academia Odoo)** (Ajustes > Usuarios y Compañías > Grupos).
5. Opcional: en cada ruta, indicad *Grupos destinatarios* para que
   aparezca como "Recomendada" solo a quien le corresponde.

## Cómo ampliar el plan

1. Academia Odoo > Aprender > Rutas formativas > abrir una ruta > pestaña
   *Lecciones* > *Añadir una línea* (o crear una ruta nueva).
2. Rellenad nivel, *Dónde se hace*, *Qué aprenderás* y los pasos (cada paso
   con su resultado esperado).
3. En *Configuración*, poned **Palabras clave** con las palabras que usaría
   un empleado al preguntar: la IA las usa para encontrar la lección.
4. Opcional: pestaña *Test de comprobación* con 2-4 preguntas (exactamente
   una respuesta correcta por pregunta).
