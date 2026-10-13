# RMS Academia Odoo

Plan de formación interno sobre **todo lo que ofrece el Odoo de RMS-Proaudio**,
de lo más básico a lo más avanzado, con **control del avance de cada
empleado** y conectado con el asistente de IA (`rms_ai_help_assistant`).

## Cómo está organizada: catálogo global, filtrado por permisos

La formación **no está organizada por departamentos**. En el código de los
módulos no hay departamentos: lo que decide qué puede hacer cada persona son
sus **grupos y menús** en Odoo, que se asignan usuario a usuario. Dos
personas del mismo departamento pueden tener accesos distintos, y alguien
puede cubrir tareas de dos áreas.

Por eso:

- Hay **un único catálogo para toda la empresa**, organizado por
  **aplicación** (Primeros pasos, Contactos, Ventas, Inventario, Gastos,
  Mapas, Portal, Empleados, Conocimiento, Administración).
- Cada lección declara qué necesita para poder ponerse en práctica
  (pestaña *Configuración*, solo visible para el Responsable de Formación):
  - **Módulo necesario**: si no está instalado, no se muestra a nadie.
  - **Menú necesario**: solo la ve quien puede ver ese menú, con el mismo
    cálculo que usa Odoo para pintar los menús (grupos del menú, permisos
    sobre el modelo de su acción y toda la cadena de menús padre).
  - **Grupos necesarios**: solo la ve quien pertenece a alguno.
  - Vacío = todos los empleados.
- Cada empleado ve **sus** lecciones (filtro *Mis lecciones*) y su progreso
  se calcula solo sobre ellas. Si mañana le dais acceso a Inventario, las
  lecciones de Inventario le aparecen solas, sin tocar la Academia.
- Puede quitar el filtro para curiosear lecciones de otras áreas: las ve con
  un aviso de que no tiene acceso y no cuentan en su plan.

## Qué ve cada persona

**Cualquier empleado** (menú **Academia Odoo > Aprender**):

- **Mi formación por aplicación**: una tarjeta por cada aplicación que usa,
  con "Completadas X de Y".
- **Mi plan de formación**: sus lecciones, agrupadas por aplicación y
  ordenadas Básico → Intermedio → Avanzado.
- **Mis lecciones pendientes** y **Mi progreso**.
- En cada lección: *Qué aprenderás*, *Dónde se hace*, *Paso a paso* (con el
  resultado esperado de cada paso), *Consejos y errores frecuentes*, y los
  botones **Empezar lección** y **Marcar como completada**. No hay tests.

**Responsable de Formación** (grupo *Responsable de Formación (Academia
Odoo)*, incluido automáticamente en los Administradores):

- Crea y edita aplicaciones, lecciones y pasos, y decide quién ve cada
  lección.
- **Control de formación > Avance por empleado**: para cada empleado, cuántas
  lecciones le corresponden según sus permisos, cuántas ha completado, en
  curso y pendientes, % de avance y última actividad. Si RRHH está
  instalado, también su departamento (para agrupar y comparar).
- **Control de formación > Detalle de lecciones completadas**: qué lección
  completó cada uno y cuándo.

Cada empleado solo ve su propio progreso (regla de registro). Un empleado no
puede crear ni modificar registros de progreso directamente: solo desde los
botones de la lección.

## Cómo encaja con la IA

El **Asistente Odoo (IA)** busca primero en la Academia (herramienta
`buscar_formacion`) ante cualquier "¿cómo hago X?", responde con los pasos
oficiales y recomienda la lección. Da prioridad a las lecciones que el
empleado puede poner en práctica; si pregunta por algo fuera de sus
permisos, se lo explica pero le avisa de que tendrá que pedir acceso.

## Contenido incluido

`data/training_content_data.xml` trae 40 lecciones redactadas a partir del
código de los módulos de este repositorio (menús, botones y comportamientos
reales). Se carga con `noupdate="1"`: lo que el Responsable de Formación
cambie desde Odoo **no se pisa** al actualizar el módulo.

Revisadlo con quien mejor conozca cada proceso: el código explica qué hace
Odoo, pero no los procedimientos que la empresa sigue "de palabra".

## Instalación

1. Copiad `rms_training_academy` (y la versión actualizada de
   `rms_ai_help_assistant`) al `addons-path`.
2. Instalad **RMS Academia Odoo** y actualizad **RMS AI Help Assistant**.
3. Añadid a quien vaya a mantener la formación al grupo **Responsable de
   Formación (Academia Odoo)** (Ajustes > Usuarios y Compañías > Grupos).

## Cómo ampliar el plan

1. Academia Odoo > Aprender > Mi formación por aplicación > abrir una
   aplicación (vista lista o formulario) > pestaña *Todas las lecciones*.
2. Rellenad nivel, *Dónde se hace*, *Qué aprenderás* y los pasos.
3. En *Configuración*, indicad quién la ve (módulo, menú y/o grupos) y unas
   buenas **Palabras clave** (la IA las usa para encontrar la lección). Para
   saber el ID externo de un menú: modo desarrollador > Ajustes > Técnico >
   Menús.
