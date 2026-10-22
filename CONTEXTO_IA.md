# Contexto para IA — repositorio `custom-rms` (Odoo de RMS-Proaudio)

> Resumen pensado para usarlo como contexto inicial de un asistente de IA que vaya a trabajar sobre este repositorio o sobre el Odoo de RMS-Proaudio. Se ha sacado del propio código (octubre de 2026). Lo marcado como **[no verificado]** es una deducción y no aparece de forma explícita en el repo.

## 1. Qué es

- **Empresa:** RMS-Proaudio (distribuidora/instaladora de equipos de audio profesional). Dominio de correo: `@rmsproaudio.com`.
- **Partner técnico:** Xtendoo (`xtendoo.es`). La organización de GitHub es `xtendoo-corporation`.
- **Repositorio:** `xtendoo-corporation/custom-rms`. Es una carpeta plana de **addons de Odoo propios**: cada subcarpeta es un módulo y no hay `requirements.txt` global, ni Docker, ni CI.
- **Versión de Odoo:** **19.0**, en edición **Enterprise** (se usan `document_knowledge`, `maintenance`, etc.). Los manifiestos usan versiones `19.0.x.y.z` (algunos antiguos ponen `1.0`).
- **Rama principal:** `19.0`, que es la que refleja producción. El trabajo se hace en ramas de feature (`claude/...`, `mapa-contacto`, …) que se integran mediante PR a `19.0`.
- **Autores principales:** Daniel del Castillo, Álvaro Jiménez Osuna y Claude (sesiones de Claude Code).
- **Idioma:** el código, los comentarios, los README y los commits están mayoritariamente en **español**. Los commits usan prefijos tipo `[IMP]`/`[FIX]`/`[REM]` o `feat(...)`/`fix(...)`.

## 2. Servidor / despliegue (lo que se deduce del repo)

- Los módulos se despliegan en el servidor de producción de Odoo y se actualizan desde *Aplicaciones* o por terminal/contenedor. El README de `rms_custom_knowledge` habla de un `docker-compose.yml` de producción con proxy inverso (Nginx/Traefik), así que **probablemente Odoo corre en Docker [no verificado]**. El repo no incluye ninguna configuración de servidor, hosts ni credenciales.
- **Addons de terceros que deben estar en el servidor** (no están en este repo):
  - OCA: `sale_triple_discount`, `sale_global_discount`, `web_responsive`.
  - Enterprise: `document_knowledge`, `maintenance`.
  - Xtendoo: `xtendoo_hr_expense_ai` (importador de gastos con IA basado en Gemini, con el wizard `hr.expense.ai.wizard`). **No se modifica**: se extiende desde los módulos `rms_hr_expense_*`.
- **Dependencias Python extra:** `openpyxl` y `Markdown`.
- **Servicios externos:**
  - API de Anthropic (`api.anthropic.com/v1/messages`), con modelos `claude-sonnet-5` y `claude-sonnet-5-5`.
  - Gemini (Google), usado por `xtendoo_hr_expense_ai` y como proveedor alternativo temporal en `rms_ai_quote_assistant`.
  - OnlyOffice Document Server (opcional, para editar hojas de cálculo en Knowledge).
  - Nominatim/OpenStreetMap con Leaflet para los mapas.
- **Enlaces internos** (`rms_web_redirect`):
  - "Sala IN": `http://192.168.11.41:8080/#/demos` (red local).
  - "CLUB": `https://club.rmsproaudio.com/admin`.
- **Correo:** `rms_mail_server` **bloquea todo el correo saliente a dominios que no sean `@rmsproaudio.com`**. Importante en pruebas: un cliente externo no recibe correos de Odoo. El alias de gastos es `expense@rmsproaudio.com`.
- **Parámetros del sistema (`ir.config_parameter`) que importan.** Las claves de API **no** están en el repo: se configuran en la base de datos.
  - `rms_ai_help_assistant.anthropic_api_key` / `.anthropic_workspace_id`
  - `rms_ai_quote_assistant.anthropic_api_key` / `.anthropic_workspace_id` / `.gemini_api_key` / `llm_provider`
  - `rms_support_error_report.anthropic_api_key` / `.anthropic_workspace_id`
  - `rms_custom_knowledge.onlyoffice_server_url` / `.onlyoffice_jwt_secret`
  - `rms_hr_expense_ai_email.min_attachment_bytes` / `.max_attempts`
- **Grupo clave:** `custom.comerciales` (Comerciales). Se creó a mano en la base de datos y **ningún módulo lo define**, pero 27 referencias del código dependen de ese XML-ID.

## 3. Módulos (34)

### IA (Claude)
| Módulo | Qué hace |
|---|---|
| `rms_ai_help_assistant` | Chat OWL: resuelve dudas de uso de Odoo y consulta datos reales (precios, stock, pedidos, documentación de Knowledge). **Es de solo lectura**: trabaja con los permisos del usuario que pregunta y nunca usa `sudo`. |
| `rms_ai_quote_assistant` | Crea presupuestos a partir de lenguaje natural. Depende de `rms_product_state` y `sale_crm`. Proveedor `anthropic` por defecto, con `gemini` como alternativa. |
| `rms_support_error_report` | Añade un botón "Notificar a soporte" en los diálogos de error. Crea `rms.support.ticket` (deduplicado, máximo 20 por usuario y hora). Un cron envía a Claude el traceback y el código fuente de los módulos implicados (incluidas las acciones de servidor guardadas en la BD) y publica el informe en Conversaciones. |
| `rms_training_academy` | "Academia Odoo": lecciones por aplicación que se filtran según los menús y grupos del usuario, con control de progreso. Está enlazada con el asistente de IA. |

### Ventas / precios / documentos
- `product_pricelist_triple_discount`: hasta 3 descuentos encadenados por regla de tarifa.
- `rms_document_format`: plantilla de impresión propia para presupuestos.
- `rms_quotation_import`: importa presupuestos desde Excel, resolviendo variantes y calculando descuentos.
- `rms_sale_catalog_no_variant_color`: quita el color de las variantes en el catálogo del presupuesto.
- `rms_sale_category_product_manager`: suscribe a los responsables de cada categoría de producto a los presupuestos.
- `rms_ventas_restriccion_comerciales`: los comerciales ven los listados pero no pueden abrir fichas de cliente o producto ni cambiar la tarifa (excepción: quien puede crear productos sí abre la ficha de producto).

### Producto / inventario
- `rms_product_state`: estados de producto (Nuevo, Demo, Ex-Demo, 2ª mano, Descontinuado) y reglas de precio por lote. Varios módulos dependen de él.
- `rms_product_import`: importa productos desde Excel con categorías jerárquicas.
- `rms_stock_barcode_scan`: escaneo de números de serie con la cámara (zxing) o con PDA hacia `stock.quant` o las líneas de albarán.
- `rms_stock_lot_label_print`: etiqueta Code128 de 10x5 cm con el número de serie.
- `stock_cession`: mercancía cedida a clientes o en ubicaciones externas.

### Contactos / CRM / mapas
- `rms_partner_multi_role`: varios roles dinámicos en los contactos hijos.
- `rms_partner_display_name`: los contactos individuales se muestran sin el prefijo de la empresa.
- `rms_partner_import`: se salta la validación del NIF en importaciones nativas. Según la academia y el asistente, el NIF debe seguir siendo válido.
- `rms_partner_equipment_model_import`: importa desde Excel los "Equipos del Cliente" de cada compañía, con histórico y log.
- `rms_customer_equipment_map`: geolocaliza clientes y los vincula con sus equipos (`maintenance`); tarjeta con persona de contacto. Tiene tests.
- `rms_global_equipment_map`: mapa global (Leaflet) de clientes con sus equipos.
- `rms_crm_hide_company_avatar`: oculta el avatar de la empresa en el kanban de CRM.

### Portal de clientes
- `rms_portal_profiles`: perfiles de portal (Cliente, Marketing, Proyectos) con acceso restringido según el perfil.
- `rms_portal_catalog`: catálogo B2B en HTML estático dentro del portal.
- `rms_portal_projects`: modelo `rms.installation.project` (app "Entregar Proyecto"). Comparte con el cliente un documento HTML en `/my/projects`. **No tiene relación con `project.project`.**
- `rms_portal_access_log`: registra accesos y lo que consulta cada cliente; envía un informe semanal.

### RR. HH. / gastos
- `rms_hr_employee_certification`: certificaciones, formaciones y consentimientos con renovación periódica (cron).
- `rms_hr_expense_ai_access`: da a `custom.comerciales` acceso al wizard de IA de gastos.
- `rms_hr_expense_ai_email`: crea un gasto por cada ticket recibido por correo; un cron cada 15 min lo procesa con la IA de Xtendoo, con reintentos.
- `rms_hr_expense_quick_capture`: app "Foto de Gasto" para fotografiar el ticket con el móvil. Lo procesa el mismo cron.

### Conocimiento / UI / varios
- `rms_custom_knowledge`: amplía Documents Knowledge con carpetas y permisos por grupo, PDF→Markdown y edición en OnlyOffice.
- `rms_chatter_hide_send_message`: oculta "Enviar mensaje" en el chatter para obligar a usar notas internas.
- `rms_comerciales_tasks_shortcut`: acceso directo a "Mis tareas" para los comerciales.
- `rms_web_redirect`: menús que abren webs externas (Sala IN, CLUB).
- `rms_mail_server`: bloqueo del correo saliente externo (ver el apartado 2).

## 4. Convenciones y advertencias para una IA

- **No modificar addons de terceros** (`xtendoo_hr_expense_ai`, OCA, Enterprise). Siempre se extienden mediante herencia desde un módulo `rms_*`.
- **Odoo 19:** `odoo` es un *namespace package*, así que `odoo.__file__` es `None` y hay que usar `__path__`. Además, `_get_product_rule(product, qty)` exige la cantidad. Hay que usar la API y las vistas de la v19 (`list` en lugar de `tree`, OWL 2).
- **Seguridad:** cada modelo nuevo necesita `security/ir.model.access.csv` y, si aplica, `ir.rule`. Los asistentes de IA trabajan **sin `sudo`**.
- **Datos que no se pueden comprobar solo con el repo:** el XML-ID `custom.comerciales`, los campos `discount1/2/3` de `sale_triple_discount` y los campos de Knowledge (`is_knowledge_document`, `body_markdown`).
- **Tests:** solo los tienen `rms_customer_equipment_map`, `rms_partner_equipment_model_import` y `rms_product_state`. Para probar en local hace falta Odoo 19.0 (`odoo/odoo`, rama `19.0`); los módulos que dependen de addons externos no se instalan sin ellos.
- **Al cambiar un módulo, subir la versión del `__manifest__.py`** para que se actualice en el servidor.
- `__pycache__` y `*.pyc` están en `.gitignore`. Existe la configuración `.serena/` (servidor LSP Python para agentes).
