# Política de perfiles de portal

La política se obtiene de los guards de listados existentes:

| Perfil | Secciones permitidas |
| --- | --- |
| customer | Presupuestos/pedidos, facturas, direcciones, catálogo B2B y proyectos de instalación |
| marketing | Proyectos y tareas nativos de Odoo, donde esté añadido como colaborador |
| projects | Proyectos de instalación |

Todos conservan conexión y seguridad. Los permisos estándar de pertenencia,
compañía y colaborador siguen aplicándose; el perfil no concede acceso por sí solo.

## Reglas globales

`security/portal_profile_rules.xml` restringe `sale.order`, `sale.order.line`,
`account.move`, `account.move.line` y `account.payment`. No tiene grupos: sus
restricciones se intersectan con las reglas estándar, aunque estas permitan el
commercial partner. Los cuatro indicadores `perm_*` son verdaderos: restringen
operaciones, sin conceder ACLs. Se incluye payment de forma preventiva; las ACLs
estándar de account 19.0 no conceden lectura de account.payment a base.group_portal.

El dominio devuelve verdadero para usuarios internos (`share=False`) o miembros
de group_portal_customer, y falso en otro caso. OdooBot y cualquier operación en
`env.su` ignoran las reglas; un usuario interno sin sudo obtiene dominio verdadero
y conserva sus restricciones estándar. No se modifica ninguna ACL.

La expresión condicional es compatible con Odoo 19: `safe_eval.py` permite los
saltos condicionales, `LOAD_ATTR` y llamadas; `ir.rule._eval_context()` proporciona
`user`, y `_compute_domain()` evalúa el dominio mediante `safe_eval`. Las reglas
globales se combinan con AND; las reglas de grupo, con OR. Los tests ejercitan el
safe_eval real y todas las ramas, además del acceso al modelo.

Los contadores estándar de sale/account usan `search_count` sin sudo y devuelven
cero para los perfiles bloqueados. No requieren capturar ni ocultar excepciones.

## Detalles, informes y tokens

Los guards heredados conservan las rutas y su autenticación original mediante
`@http.route()`. Pedido y factura redirigen a `/my` para usuarios portal
autenticados sin group_portal_customer, incluso con access_token o report_type=pdf.
Detalle y archivo de instalación permiten customer/projects con las comprobaciones
de propiedad y estado del controlador original; marketing se redirige a `/my`.
Los nuevos guards no restringen usuarios internos.

Los visitantes anónimos pasan al controlador estándar. En Odoo 19,
`CustomerPortal._document_check_access()` intenta `check_access('read')`; si falla,
valida el token contra el documento obtenido con `with_user(SUPERUSER_ID)` y
devuelve ese documento. `_show_report()` renderiza con sudo después de esa
validación. Por ello los enlaces de email válidos siguen funcionando sin sesión,
aunque el usuario público (`share=True`) no supere las reglas ordinarias. El
bypass público del guard NO concede acceso: sin token válido se mantiene la
comprobación estándar. El endpoint directo `/report/pdf/...` requiere sesión y
renderiza con el entorno del solicitante: se aplican las reglas de registro.

Fuentes revisadas en la rama oficial 19.0:
- https://github.com/odoo/odoo/blob/19.0/odoo/tools/safe_eval.py
- https://github.com/odoo/odoo/blob/19.0/odoo/addons/base/models/ir_rule.py
- https://github.com/odoo/odoo/blob/19.0/addons/portal/controllers/portal.py
- https://github.com/odoo/odoo/blob/19.0/addons/sale/controllers/portal.py
- https://github.com/odoo/odoo/blob/19.0/addons/account/controllers/portal.py
- https://github.com/odoo/odoo/blob/19.0/addons/account/security/ir.model.access.csv
- https://github.com/odoo/odoo/blob/19.0/addons/web/controllers/report.py

## Pruebas

`TestPortalProfileSecurity` está en el archivo de tests ya descubierto
`tests/test_installation_project.py`, sin añadir imports a ningún `__init__.py`.
Usa HttpCase y el fixture contable AccountTestInvoicingCommon, con etiquetas
post_install y -at_install. Crea una empresa cliente, contactos portal de cada
perfil bajo el mismo commercial partner, un pedido confirmado y una factura
publicada. Comprueba ORM, líneas, safe_eval, usuarios internos, sudo, detalles,
tokens anónimos/autenticados, PDF directo, contadores y archivos de instalación.

La suite necesita un servidor/base de datos Odoo 19. No se ha ejecutado en este
entorno: no hay paquete Odoo local y no se permite ejecutar Docker. Las
comprobaciones locales son compilación Python, parseo XML y git diff --check.
