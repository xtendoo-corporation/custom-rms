# Auditoría Odoo custom-rms — 24/10/2026

No hay hallazgos críticos, pero sí 17 altos. Lo más urgente:
- los comerciales pueden saltarse por RPC el bloqueo de precios y descuentos;
- cualquier empleado puede leer adjuntos ajenos a través del cron de gastos con IA;
- el mapa global expone todos los contactos;
- los importadores duplican o borran datos.

**Alcance:** auditoría estática, de solo lectura, de los 36 módulos en el commit `0757c5b` (rama `claude/seguridad-portal-s3-s6`, que incluye el PR #52). No se ha ejecutado Odoo. Todos los hallazgos altos y los medios principales se han comprobado en el código (marcados con ✔). "A verificar" significa que depende de la configuración o de código de terceros que no está en el repo. El servidor de producción no está incluido (ver sección 8).

## 1. Prioridades (hallazgos altos)

| # | Hallazgo | Dónde | Impacto |
|---|---|---|---|
| A1 ✔ | La restricción de comerciales solo existe en la interfaz | `rms_ventas_restriccion_comerciales/models/sale_order.py:21-49` | Un comercial cambia `price_unit`, `discount*`, `tax_ids`, `pricelist_id` y `fiscal_position_id` con `write` por RPC, y lee tarifas, costes y fichas completas con `search_read` |
| A2 ✔ | Lectura de cualquier adjunto (IDOR) a través del cron de gastos con IA | `rms_hr_expense_ai_email/models/hr_expense.py:41,184-197` | Un empleado pone `ai_source_attachment_id` = id de una nómina o contrato ajeno; el cron lo lee con `sudo`, lo manda a Gemini y escribe los datos en su gasto y en el chatter |
| A3 ✔ | El mapa global devuelve con `sudo` todos los contactos (y su exportación a XLSX) | `rms_global_equipment_map/controllers/main.py:17-25,61-86` | Cualquier usuario interno obtiene nombre, email y teléfono de los partners de todas las compañías |
| A4 ✔ | `cr.commit()` cada 100 productos en el importador | `rms_product_import/wizard/product_import_wizard.py:237` | Si la importación falla a mitad, lo ya procesado queda guardado |
| A5 ✔ | Importar contactos borra datos | `rms_partner_import/wizard/partner_import_wizard.py:86-125,232` | Las columnas que faltan se escriben como `''` sobre contactos existentes |
| A6 | Importar contactos crea duplicados | `partner_import_wizard.py:187,223` | Solo reconoce un contacto existente si coinciden a la vez CIF, nombre y nombre comercial; dos filas iguales del fichero se crean dos veces |
| A7 ✔ | Reimportar presupuestos los duplica | `rms_quotation_import/wizard/quotation_import_wizard.py:387` | No busca si el presupuesto ya existe |
| A8 | Un presupuesto hereda la cabecera del anterior | `quotation_import_wizard.py:74-121` | Si una fila trae el cliente vacío, se usan el cliente, la fecha y el comercial del pedido anterior |
| A9 | Los números inválidos se aceptan sin avisar | `product_import_wizard.py:129,268`, `quotation_import_wizard.py:167` | Un precio ilegible pasa a 0, `"1.250,50"` se cambia por el precio de tarifa y una cantidad inválida pasa a 1 |
| A10 | Cliente o variante ambiguos | `quotation_import_wizard.py:259,535,609` | Se elige con `limit=1` sin avisar |
| A11 ✔ | Grupo `custom.comerciales` no definido en ningún módulo | `rms_ventas_restriccion_comerciales/models/restrictions.py:3` y otros | La instalación en una base nueva o en staging falla |
| A12 ✔ | Quedan 5 `_sql_constraints`, que Odoo 19 ignora | `rms_hr_employee_certification`, `rms_custom_knowledge`, `rms_product_state` | No se garantiza la unicidad |
| A13 ✔ | `cr.rollback()` dentro de una petición RPC | `rms_ai_quote_assistant/models/ai_quote_assistant.py:610` | Deshace toda la transacción y devuelve al usuario el texto interno del error |
| A14 ✔ | `rms_partner_import/models` no se carga nunca | `rms_partner_import/__init__.py` | Las funciones que describe el manifest no existen |
| A15 | Dependencias externas sin fijar | `sale_triple_discount`, `sale_global_discount`, `document_knowledge`, `xtendoo_hr_expense_ai` | No se puede reproducir la instalación; `web_responsive` sobra |
| A16 ✔ | Se puede duplicar una salida de stock | `stock_cession/models/stock_cession.py:94` | `action_draft` no comprueba el estado; al confirmar de nuevo se genera un segundo albarán (gravedad media-alta) |
| A17 ✔ | XSS almacenado en la vista previa de `.md` de Knowledge | `rms_custom_knowledge/models/ir_attachment.py:53-56,1147` | `sanitize=False` y `markdown` con la extensión `extra`: un `.md` subido ejecuta JS al abrirlo un administrador (a verificar si `markdown` está instalado) |

## 2. Portal y rutas públicas

No hay ningún IDOR directo en el portal. Las comprobaciones de propiedad, el CSP sandbox, las reglas de perfil, el anti path traversal, el JWT de OnlyOffice y la protección anti-SSRF están bien hechos.

| Gravedad | Hallazgo | Dónde | Arreglo |
|---|---|---|---|
| Media ✔ | Un gestor de "Entregar Proyecto" da acceso al portal a cualquier contacto y ve el enlace de registro, así que puede entrar como ese cliente | `rms_portal_profiles/wizard/portal_invite_link.py:23-79` | **Lo decides tú:** exigir `base.group_partner_manager` o enviar el enlace solo por email |
| Media ✔ | XSS en `.md` (= A17) | `ir_attachment.py` | `html_sanitize()` |
| Media | El registro de accesos guarda IPs, búsquedas y scoring sin retención; lo lee cualquier usuario interno de cualquier compañía | `rms_portal_access_log` | Cron de purga, grupo propio y regla multicompañía |
| Media ✔ | Cualquier empleado puede enviarse el informe semanal completo | `portal_weekly_report_data.xml:10`, `portal_weekly_report.py:37` | Exigir `group_portal_weekly_report` |
| Media ✔ | El catálogo devuelve al cliente las notas internas (`product.description`) | `rms_portal_catalog/controllers/portal.py:321` | Usar `description_sale` |
| Baja | `/my/portal/track` con `csrf=False` y sin límite de peticiones | `rms_portal_access_log/controllers/portal.py:35` | Quitar `csrf=False` y añadir un límite |
| Baja | `web.max_file_upload_size` = 1 GiB (el comentario dice 512 MiB) en un XML que además no se carga | `rms_custom_knowledge/data/ir_config_parameter_data.xml` | Valor por defecto o borrar el XML |
| Baja | El callback de OnlyOffice no liga el cuerpo al JWT; el token de contenido dura 12 h y va en la URL | `onlyoffice.py` | Usar el payload del JWT; `exp` de minutos |
| Baja | Una ruta GET de administración del catálogo crea registros; un `sortby` inválido da error 500 | `rms_portal_catalog/controllers/portal.py` (`/my/catalog/admin/card`), `rms_portal_projects/controllers/portal.py:67` | POST con CSRF; `.get()` |

## 3. IA, secretos e integraciones

No hay claves hardcodeadas: todas están en `ir.config_parameter` y solo las lee el administrador. Todas las llamadas HTTP tienen timeout y ninguna usa `verify=False`. Nada de lo que devuelve el LLM se ejecuta.

| Gravedad | Hallazgo | Dónde | Arreglo |
|---|---|---|---|
| Alta ✔ | IDOR de adjuntos en gastos (= A2) | `rms_hr_expense_ai_email/models/hr_expense.py` | Exigir que el adjunto sea del propio gasto (`res_model`/`res_id`); campo `readonly` |
| Media ✔ | La clave de Gemini va en la URL y `_logger.exception` la vuelca en los logs | `rms_ai_quote_assistant/models/ai_quote_assistant.py:434,881` | Mandarla en la cabecera `x-goog-api-key` |
| Media | El asistente de ayuda enseña tarifas y Dto1/2/3 a comerciales sin permiso de tarifas | `rms_ai_help_assistant/models/ai_help_assistant.py:498,545-584` | Omitirlos si `hide_pricelists()` |
| Media | El asistente de presupuestos envía el email y el teléfono de todos los contactos al LLM en cada mensaje | `ai_quote_assistant.py:635,813` | Enviar solo `id`/`name` |
| Baja | `confirm_quote` usa los lotes y precios que manda el cliente, no los de la vista previa | `ai_quote_assistant.py:557-608` | Construir el pedido desde `preview` |
| Baja | Soporte: con un traceback falso se lee el código de cualquier acción de servidor y se envía a la IA | `rms_support_error_report/models/support_ticket.py:498-567` | Filtrar las acciones por permisos |
| Baja / a verificar | Gastos por email: el remitente no se autentica y el resultado se aplica con `sudo` | `hr_expense.py:45-66` | Aceptar solo remitentes empleados y usar `with_user` |
| A verificar | El ACL del wizard de IA para comerciales depende de lo que haga `xtendoo_hr_expense_ai` | `rms_hr_expense_ai_access/security/ir.model.access.csv` | Revisar el código de xtendoo |

## 4. Permisos internos

Todos los modelos nuevos tienen ACL. El problema está en ACL demasiado amplias y en reglas que faltan.

| Gravedad | Hallazgo | Dónde | Arreglo |
|---|---|---|---|
| Alta ✔ | Restricción de comerciales solo en la interfaz (= A1) | `rms_ventas_restriccion_comerciales` | Validar en `write`/`create` de `sale.order` y sus líneas; `ir.rule` en `product.pricelist.item`; `groups=` en los campos sensibles |
| Alta ✔ | Mapa global con `sudo` (= A3) | `rms_global_equipment_map` | Leer sin `sudo` o exigir un grupo |
| Media ✔ | `stock_cession`: duplicado de salidas, sin `company_id` y los usuarios de stock pueden borrar cesiones hechas | `stock_cession/models/stock_cession.py:44-96` | Restringir `action_draft`, añadir regla multicompañía, quitar `unlink` |
| Media | Los Knowledge Uploaders ven nombres de documentos de carpetas restringidas | `rms_custom_knowledge/models/ir_attachment.py:261-353` | Filtrar a los contributors por `readable_ids` |
| Media ✔ | Certificaciones de RR. HH. sin regla multicompañía (`[(1,'=',1)]`) | `rms_hr_employee_certification/security/*.xml:13,20` | Regla `company_id in company_ids` |
| Media | Quien tiene "Puede geolocalizar" ve todos los contactos; cualquier usuario interno ve los equipos con su nº de serie | `rms_customer_equipment_map/models/res_partner.py:117,641` | Usar `sudo` solo para los contadores |
| Media | `product.state` y `sale.order.line.serial` con CRUD para `base.group_user`: se puede cambiar el código de un estado y fijar `price_unit` (otra forma de saltarse A1) | `rms_product_state` | ACL solo de lectura y validar `price_unit` |
| Baja | Cualquier empleado puede cambiar `rms.partner.role` (direcciones de factura y entrega) | `rms_partner_multi_role` | CRUD solo para gestores |
| Baja | Cualquier usuario interno ve el mapa de permisos de Knowledge | `rms_custom_knowledge/security/security.xml:59` | Limitar la regla |
| Baja | Un usuario puede marcar como hecha cualquier lección de la Academia | `rms_training_academy/models/training_lesson.py:236` | Filtrar por lecciones disponibles |

## 5. Importadores

No hay `sudo`, `eval` ni `pickle`. El importador de equipos comprueba el grupo administrador. Los hallazgos altos están en la sección 1 (A4–A10).

| Gravedad | Hallazgo | Dónde |
|---|---|---|
| Media | Referencias y proveedores ambiguos de productos se resuelven sin avisar | `product_import_wizard.py:107,120` |
| Media | Equipos: con una sola palabra en común (por ejemplo "Control") se asocia automáticamente | `equipment_model_import_wizard.py:499` |
| Media | Equipos: si salta una excepción sin savepoint, quedan asociaciones a medias | `equipment_model_import_wizard.py:127,534` |
| Media | Ningún importador limita el tamaño, las filas ni la expansión ZIP | los 4 wizards |
| Media | Búsquedas fila a fila (N+1) y `create` registro a registro | `product_import_wizard.py:341`, `quotation_import_wizard.py:409` |
| Media | Las fórmulas sin valor calculado llegan como `None`: precio 0, filas omitidas | `load_workbook(data_only=True)` |
| A verificar | XXE según las versiones de openpyxl/lxml instaladas | — |

## 6. Frontend JS/OWL

Las rutas de import de Odoo 19 son correctas. No hay XSS: los mapas usan `textContent` y los asistentes `t-out` sin `markup`. No se carga nada desde CDN.

| Gravedad | Hallazgo | Dónde |
|---|---|---|
| Media-alta | La cámara se queda encendida si se sale antes de que responda `getUserMedia` | `rms_stock_barcode_scan/static/src/stock_barcode_scan/stock_barcode_scan.js:274-315,547` |
| Media | Bucle infinito de `requestAnimationFrame` en el modo PDA | `stock_barcode_scan.js:146-177` |
| Media ✔ | La cola de actualizaciones del catálogo se bloquea tras un error de RPC y deja de guardar | `rms_sale_catalog_no_variant_color/static/src/product_catalog_list/order_line_widget.js:55-63` |
| Media ✔ | Mapa global con `sudo` (= A3) | — |
| Baja | Las teselas de OpenStreetMap usan subdominios `{s}` y exponen la IP del usuario a terceros | `customer_equipment_map.js:174`, `global_equipment_map.js:280` |
| Baja | El límite de avisos a soporte se salta repitiendo el mismo error | `support_ticket.py:237-268` |
| Baja | Temporizadores de búsqueda sin limpiar y `_loadInitial` sin `catch` | `stock_barcode_scan.js:87,211,227` |

## 7. Calidad y mantenibilidad

| Gravedad | Hallazgo | Dónde / arreglo |
|---|---|---|
| Alta | A11–A15 | Ver la sección 1 |
| Media | Siete manifests sin el prefijo `19.0.`, dos sin `author`, uno sin `license`; autores y licencias mezclados (AGPL/LGPL) | Normalizar |
| Media | `init()` que hace `UPDATE` masivo en cada `-u` (machaca los colores editados a mano) | `rms_sale_catalog_no_variant_color/models/product_attribute_value.py:35`, `rms_custom_knowledge/models/ir_attachment.py:31` → pasar a migraciones |
| Media | `ir_config_parameter_data.xml` no está en el manifest | `rms_custom_knowledge` |
| Media | Crons poco robustos: actividad de renovación que se repite sin fin, cron de estados sin lotes, notificación de soporte fuera del `try`, informe semanal que puede enviarse dos veces | `rms_hr_employee_certification`, `rms_product_state`, `rms_support_error_report`, `rms_portal_access_log` |
| Media | Sin tests en módulos críticos: `rms_ventas_restriccion_comerciales`, `product_pricelist_triple_discount`, los importadores, `rms_support_error_report`, `rms_stock_barcode_scan`, `stock_cession` | Priorizar los de permisos y precios |
| Media | Sobrescritura global de `_search` de productos dentro de un módulo de importación | `rms_product_import/models/product_product.py` |
| Baja | APIs obsoletas: `odoo.osv.expression`, `type='json'` y 99 `t-esc` | Migrar a `Domain`, `jsonrpc` y `t-out` |
| Baja | SQL con `%` para el nombre de tabla (no explotable) | `rms_portal_access_log/models/portal_interest.py:65` |
| Baja | Código muerto | `rms_product_import/wizard/test_partner_creation.py` |
| Baja ✔ | Higiene del repo: 3 `.DS_Store`, `.claude/` y `.serena/` versionados; `.gitignore` mínimo; `Claude outputs/` (sin trackear) contiene un CSV con datos de RR. HH.; sin pre-commit ni CI | `.gitignore`, `git rm --cached`, pre-commit de OCA |
| Baja | `docker-compose.yml` con `odoo/odoo` y el puerto 8069 abierto en 0.0.0.0 | Solo vale para desarrollo: `127.0.0.1:8069` y `.env` |

## 8. Revisión independiente de Codex

Codex repitió las revisiones 1, 2, 3, 5 y 6 sin ver este informe. Confirma A1, A2, A3, A4, A11, A12, A13, A14, A16 y A17, y casi todos los medios. Aporta además estos hallazgos:

| Gravedad | Hallazgo | Dónde | Arreglo |
|---|---|---|---|
| Alta ✔ | XSS almacenado en el catálogo del portal: nombre, email y teléfono del comercial van a `innerHTML` sin escapar. Cualquier usuario interno edita sus propios datos y el JS se ejecuta en la sesión de portal de sus clientes | `rms_portal_catalog/catalog_private/index.html:715-731` (datos de `controllers/portal.py:85-93`) | Construir con `textContent` y validar `mailto:`/`tel:` |
| Media | El carrito del portal no filtra por compañía | `rms_portal_catalog/controllers/portal.py:334-346` | Filtrar por la compañía y usar `with_company()` |
| Media (Codex: alta) | Soporte: un traceback inventado hace leer con `sudo` el código de cualquier acción de servidor y lo envía a Anthropic | `rms_support_error_report/models/support_ticket.py:202,498,565` | No elegir código privilegiado a partir de datos del cliente |
| Media | Soporte: la URL completa (con `access_token`) y el diagnóstico se guardan y se envían a Anthropic sin redactar | `rms_support_error_report/static/src/support_report/support_report.js:40`, `support_ticket.py:375` | Quitar tokens y parámetros sensibles |
| Media / a verificar | `rms_mail_server` descarta los correos a destinatarios externos pero los da por enviados; si hay destinatarios mezclados, tampoco reciben los internos | `rms_mail_server/models/ir_mail_server.py:30` | Confirmar si es intencionado (entorno de pruebas); si no, fallo explícito |
| Media | Los gastos de correo sin adjunto procesable se quedan para siempre en la cola del cron y pueden bloquear a los siguientes | `rms_hr_expense_ai_email/models/hr_expense.py:152,187` | Estado terminal «sin adjunto» y orden explícito |
| Media (Codex: alta) | `sale.order.line.serial`: CRUD para cualquier usuario interno, sin reglas del pedido ni de compañía | `rms_product_state/security/ir.model.access.csv:3` | Restringir el ACL y añadir reglas equivalentes a las del pedido |
| Media | Las lecciones de la Academia no disponibles para el usuario se pueden leer por RPC | `rms_training_academy/security/ir.model.access.csv:4`, `models/training_lesson.py:217` | Regla de lectura según disponibilidad |
| Media | Falta `external_dependencies` con `openpyxl` en los importadores | `rms_product_import/__manifest__.py` | Declararlo |

Diferencias de criterio: Codex considera correcto el enlace de invitación al portal, que aquí sigue pendiente de tu decisión. También sube a alta la falta de multicompañía en las certificaciones.

## 9. Pendiente

- **Servidor de producción:** no auditado. Faltan el acceso SSH, el tipo de despliegue y la URL.
- **Fase 2 (correcciones):** pendiente de aprobar el plan de correcciones.
