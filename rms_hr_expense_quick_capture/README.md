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
   alias de email).
2. Se dispara **al momento** (sin esperar al cron) el mismo motor de IA que
   usa `rms_hr_expense_ai_email` (`hr.expense.ai.wizard` de
   `xtendoo_hr_expense_ai`), reutilizando su lógica de extracción,
   categorización por palabras clave y aviso de fallo ("NO ES POSIBLE
   ESCANEARLO" si no se puede procesar) — no se reimplementa nada.
3. Si la IA falla, el propio `hr.expense` se marca con "Correcciones de IA
   Pendientes" y el cron de `rms_hr_expense_ai_email` lo recogerá para
   reintentarlo automáticamente más adelante (hasta el límite de intentos
   configurado), igual que con los gastos llegados por correo.

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
