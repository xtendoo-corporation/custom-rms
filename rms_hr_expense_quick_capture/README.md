# RMS HR Expense Quick Capture

## Qué hace

Añade una app "Foto de Gasto" (visible en el selector de aplicaciones de
Odoo): una pantalla propia (client action OWL, sin la barra/breadcrumb
habitual de Odoo) con un único botón grande centrado para hacer la foto.
Al tocarlo se abre directamente la cámara del móvil (input de archivo con
`capture="environment"`, sin necesidad de pedir permisos de cámara vía
JavaScript ni de streaming de vídeo).

En cuanto se hace la foto, se sube sola (sin botón de confirmación
aparte):

1. Se crea un `hr.expense` en borrador a nombre del empleado asociado al
   usuario que ha entrado (no depende del remitente de un correo, como el
   alias de email), y se guarda la foto como su adjunto de IA
   (`ai_source_attachment_id`).
2. La pantalla confirma al momento que la foto se ha subido y el gasto se
   ha creado — **no espera a la IA en esa misma petición**: una foto real
   desde el móvil (4G) más el tiempo que tarda Gemini puede superar el
   timeout del proxy/la conexión, y esa espera no debe arriesgar que se
   pierda la subida. El análisis con IA lo hace el cron ya existente de
   `rms_hr_expense_ai_email` (generalizado para recoger cualquier gasto
   con `ai_source_attachment_id`, no solo los llegados por correo),
   reutilizando el mismo motor (`hr.expense.ai.wizard` de
   `xtendoo_hr_expense_ai`) sin reimplementar nada.
3. Si la IA falla, el propio `hr.expense` se marca con "Correcciones de IA
   Pendientes" y ese mismo cron lo reintenta automáticamente más adelante
   (hasta el límite de intentos configurado), igual que con los gastos
   llegados por correo.

## Pensado para acceso directo en el móvil

Mínimo número de toques: abrir la app → tocar el botón → hacer la foto →
confirmar en la cámara nativa → listo (sin ningún paso más). Guardando la
URL de esta acción como acceso directo en la pantalla de inicio del móvil
("Añadir a pantalla de inicio"), queda como un icono más, similar a una
app nativa.

## Dependencias

Depende de `hr_expense`, `xtendoo_hr_expense_ai` y `rms_hr_expense_ai_email`
(reutiliza directamente su método `_rms_run_ai_import` y el campo
`ai_source_attachment_id`, en vez de duplicar la lógica de llamada a la
IA).
