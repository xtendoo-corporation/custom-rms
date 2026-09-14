# RMS HR Expense AI Access

## Qué hace

El módulo de terceros **Xtendoo HR Expense AI** (`xtendoo_hr_expense_ai`)
añade el botón "Importar con IA" en Gastos, que abre el wizard
`hr.expense.ai.wizard` para extraer los datos de un ticket con IA y crear el
gasto automáticamente. Por defecto, ese módulo restringe el acceso a ese
wizard únicamente al grupo **Gastos / Todos los aprobadores**
(`hr_expense.group_hr_expense_team_approver`): un comercial normal ve el
botón pero al pulsarlo obtiene un "Error de acceso".

Este módulo **no modifica el código de xtendoo_hr_expense_ai** (es un
addon de terceros y cualquier cambio ahí se perdería en la próxima
actualización). En su lugar, añade una línea adicional de
`ir.model.access.csv` que concede acceso (lectura/escritura/creación, sin
borrado) sobre `hr.expense.ai.wizard` al grupo de comerciales
(`custom.comerciales`).

## Por qué es seguro

- Solo se amplía el acceso al **wizard de importación**, no a ningún
  permiso de aprobación de gastos.
- La visibilidad y las reglas de registro (`ir.rule`) del propio modelo
  `hr.expense` no se tocan: un comercial solo puede seguir creando y viendo
  **sus propios** gastos, igual que ya podía hacer manualmente desde
  "Nuevo" o por email a `expense@rmsproaudio.com`. Este módulo simplemente
  habilita una vía adicional (la IA) para rellenar ese mismo formulario.
- El grupo `custom.comerciales` no está definido por ningún módulo de este
  repositorio: es un grupo creado manualmente en Ajustes > Técnico >
  Grupos y usado ya como referencia externa en `rms_ventas_restriccion_comerciales`
  y `rms_ai_help_assistant`. Si ese grupo no existe en una base de datos
  concreta, la instalación de este módulo fallará al no poder resolver el
  external id — instalarlo solo tiene sentido en bases de datos donde
  `custom.comerciales` ya exista.

## Dependencia de terceros

Este módulo depende de `xtendoo_hr_expense_ai`. Si esa app se desinstala o
se sustituye por otra, esta regla de acceso deja de tener efecto y debería
revisarse o eliminarse.
