# RMS HR Expense Quick Capture

## Qué hace

Añade una app "Foto de Gasto" (visible en el selector de aplicaciones de
Odoo) con una única pantalla: un campo de imagen y un botón "Crear gasto".

Al elegir/hacer una foto y pulsar el botón:

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

Al entrar en esta acción desde un navegador móvil (Chrome/Safari), el
selector de imagen del formulario ya ofrece la cámara como opción nativa
del sistema operativo — no hace falta ningún JavaScript adicional para
abrir la cámara. Guardando la URL de esta acción como acceso directo en la
pantalla de inicio del móvil ("Añadir a pantalla de inicio"), queda como un
icono más, similar a una app nativa.

## Dependencias

Depende de `hr_expense`, `xtendoo_hr_expense_ai` y `rms_hr_expense_ai_email`
(reutiliza directamente su método `_rms_run_ai_import` y el campo
`ai_source_attachment_id`, en vez de duplicar la lógica de llamada a la
IA).
