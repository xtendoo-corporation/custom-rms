# RMS HR Expense AI Email Import

## Qué hace

El alias `expense@rmsproaudio.com` crea un `hr.expense` en borrador por cada
correo entrante, pero solo parseaba el asunto y amontonaba todos los
adjuntos en un único gasto. Este módulo:

1. Cuando un correo trae varios tickets (imagen o PDF), reparte los
   adjuntos en un `hr.expense` en borrador por cada uno, en vez de uno solo
   con todo junto. Se ignoran adjuntos pequeños (por defecto < 15 KB,
   parámetro `rms_hr_expense_ai_email.min_attachment_bytes`) para no crear
   un gasto de más por cada logo de firma embebido en el correo.
2. Por cron (cada 15 minutos, para no acoplar la llamada a Gemini a la
   recepción del correo), llama al mismo asistente **"Importar con IA"**
   del módulo de terceros `xtendoo_hr_expense_ai`
   (`hr.expense.ai.wizard`: `action_analyze()` + `action_apply()`) sobre el
   adjunto que ya llegó por correo, sin pedir que se vuelva a subir a mano.
3. Deja el gasto en `draft`, sin tocar el flujo de aprobación.
4. Reintenta hasta `rms_hr_expense_ai_email.max_attempts` veces (3 por
   defecto). Si tras agotarlas sigue sin poder procesarse, deja un mensaje
   en el chatter del gasto y marca "Correcciones de IA Pendientes"
   (`ai_has_corrections`, campo ya existente) para que administración lo
   revise a mano.
5. Usa los campos ya existentes de `xtendoo_hr_expense_ai`
   (`ai_processed`, `ai_has_corrections`) en vez de duplicarlos. Si tras
   aplicar los datos de la IA el gasto sigue sin categoría (`product_id`),
   la asigna por palabras clave sobre el `default_code` existente (COMM,
   EXP_GEN, FOOD, GIFT, MIL, TRANS & ACC), sin pisar nunca una categoría ya
   asignada.

## Parámetros de sistema (opcionales, con valores por defecto si no se crean)

- `rms_hr_expense_ai_email.min_attachment_bytes` (por defecto `15000`)
- `rms_hr_expense_ai_email.max_attempts` (por defecto `3`)
- `rms_hr_expense_ai_email.batch_limit` (por defecto `20`, gastos procesados
  por ejecución del cron)

## Por qué es seguro

- No toca `mail.alias` ni su seguridad de contacto ("Empleados
  autenticados" sigue restringiendo la creación a gente con correo
  `@rmsproaudio.com`).
- No toca el flujo de aprobación: los gastos siempre quedan en `draft`,
  igual que ahora.
- No reimplementa la llamada a Gemini: reutiliza tal cual el wizard
  `hr.expense.ai.wizard` de `xtendoo_hr_expense_ai`, el mismo que ya usa el
  botón manual "Importar con IA".

## Dependencia de terceros

Este módulo depende de `xtendoo_hr_expense_ai` (modelo `hr.expense.ai.wizard`
con los métodos `action_analyze()`/`action_apply()` y los campos
`attachment_file`, `attachment_name`, `expense_id`, `state`). Si esa app se
desinstala o cambia esa API, el cron de este módulo dejará de poder
procesar tickets y debería revisarse.
