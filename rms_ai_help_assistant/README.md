# RMS AI Help Assistant

Chat de IA (Claude) integrado en Odoo 19.0 para que cualquier empleado de
RMS-Proaudio pregunte cómo se hace algo (crear un cliente, asignar una
lista de precios, etc.) y consulte datos reales (precio para un cliente
concreto, stock, estado de un pedido, documentación interna), en modo
**estrictamente de solo lectura**.

## Por qué no hace falta ni un usuario nuevo ni un servidor aparte

- Corre **dentro de vuestro Odoo**, en el mismo servidor donde ya tenéis
  instalados el resto de módulos `rms_*`. No hay que montar ni mantener
  ninguna infraestructura adicional.
- Se ejecuta siempre bajo los permisos del **usuario que pregunta**
  (`self.env`, nunca `sudo()`), igual que `rms_ai_quote_assistant`. No hace
  falta crear ningún usuario de servicio ni una API key de Odoo dedicada:
  usa la sesión normal de quien esté usando el chat.
- La única credencial nueva que necesitáis es una **API key de Anthropic**
  (ver más abajo).

## Por qué es seguro (no puede escribir nada)

Ninguna de las herramientas que el modelo puede usar llama a
`create` / `write` / `unlink`. Todas son búsquedas de solo lectura
(`search`, `search_read`, cálculo de precio de una tarifa). El código está
comentado explícitamente en `models/ai_help_assistant.py` en los puntos
relevantes. Si un empleado le pide al chat que "cree un cliente" o "cambie
un precio", el asistente está instruido (y no tiene herramientas) para
explicar los pasos manuales en vez de ejecutarlos.

También incluye una guarda específica para el grupo `custom.comerciales`:
como la restricción de ese grupo para no ver la ficha completa de
cliente/producto es solo de vista (no de `ir.model.access`), el propio
código de la herramienta `buscar_cliente` oculta email/teléfono/NIF para
ese grupo, para no abrir por el chat lo que la interfaz ya les oculta.

## Instalación

1. Copia la carpeta `rms_ai_help_assistant` a vuestro `addons-path` junto
   al resto de módulos `rms_*`.
2. Actualiza la lista de aplicaciones e instala **RMS AI Help Assistant**.
3. Ve a **Ajustes > Técnico > Parámetros del sistema** y crea (o revisa):
   - `rms_ai_help_assistant.anthropic_api_key` — vuestra clave de la API
     de Anthropic. Si ya tenéis configurada
     `rms_ai_quote_assistant.anthropic_api_key`, no hace falta que la
     repitáis: este módulo la reutiliza automáticamente si no encuentra la
     suya propia.
   - `rms_ai_help_assistant.anthropic_model` — ya viene con
     `claude-sonnet-5` por defecto; cámbialo si queréis otro modelo.
   - `rms_ai_help_assistant.anthropic_workspace_id` — solo si vuestra API
     key es de las "identity-linked" de un workspace de la consola de
     Anthropic (igual que en `rms_ai_quote_assistant`).
4. El menú **Asistente Odoo (IA)** aparece para cualquier usuario interno
   (`base.group_user`). Ajusta el grupo en
   `views/ai_help_assistant_menus.xml` si queréis restringirlo más.

## Qué sabe y qué no

El prompt (`SYSTEM_PROMPT` en `models/ai_help_assistant.py`) incluye ya las
reglas de negocio que se pudieron extraer de vuestros módulos personalizados
en esta primera revisión: roles múltiples de contacto, triple descuento en
tarifas, estados de producto (Demo/Ex-Demo/2ª Mano/Descontinuado),
restricción de comerciales, importación de contactos sin validación de
NIF, cesiones de stock, bloqueo de correo saliente a dominios externos, y
la existencia de plantillas de impresión y wizards de importación propios.

Esto es una primera versión: conviene revisarlo con quien mejor conozca
cada proceso interno y ampliarlo con matices que no estén reflejados solo
en el código (por ejemplo, procedimientos que se siguen "de palabra" y no
están en ningún módulo). La herramienta `buscar_documentacion` ya está
lista para consultar en vivo lo que vayáis documentando en el módulo
**RMS Custom Knowledge**, así que otra vía de ampliarlo con el tiempo es
simplemente ir documentando ahí los procedimientos, sin tocar código.

## Probado localmente (2026-09-07)

Este módulo se probó en una instancia Odoo 19.0 real (fuente oficial
`odoo/odoo`, rama `19.0`) instalada en un entorno local aislado, junto con
la mayoría de módulos `rms_*` de este repositorio (todos salvo los que
dependen de addons que no están en este repositorio: `rms_custom_knowledge`
depende de `document_knowledge`, `product_pricelist_triple_discount` de
`sale_triple_discount`, y `rms_comerciales_tasks_shortcut` de
`web_responsive` — probablemente módulos de Enterprise/OCA presentes en
vuestro servidor real pero no en este repo). Resultado:

- Instala sin errores junto con `base`, `web`, `sale`, `stock` y el resto
  de `rms_*` instalables.
- El menú y el chat (componente OWL) cargan correctamente en el navegador,
  sin errores de JS ni de consola.
- El flujo completo cliente → `orm.call` → `send_message` → Anthropic
  funciona de extremo a extremo: probado sin API key (mensaje de error
  correcto) y con una API key inválida (llega a hacer la petición HTTP real
  a `api.anthropic.com`, recibe un 401 y lo maneja sin romperse).
- **Se encontró y corrigió un bug real**: `pricelist._get_product_rule(product=product)`
  fallaba siempre en Odoo 19.0 con `TypeError: _compute_price_rule() missing
  1 required positional argument: 'quantity'` (quedaba silenciado por el
  `except Exception` de alrededor, así que no rompía la respuesta al
  usuario, pero el desglose de descuentos encadenados nunca se calculaba).
  Corregido a `pricelist._get_product_rule(product, 1.0)`, verificado que
  ahora calcula bien el precio con descuento (probado con una regla de
  tarifa al 15%) y que sigue funcionando sin lista de precios, con IDs
  inexistentes y con producto en estado Demo.

## Pendiente de probar en vuestro entorno real

Lo único que no se ha podido verificar en este entorno local, por
depender de addons que no están en este repositorio:

- El desglose de los 3 descuentos encadenados (`discount1`/`discount2`/
  `discount3`) tal cual los define `sale_triple_discount` +
  `product_pricelist_triple_discount`: la lógica ya no falla, pero solo se
  ha probado con el descuento simple estándar de Odoo (`price_discount`),
  no con esos campos concretos.
- El external id `custom.comerciales` del grupo de Comerciales: confirmad
  que sigue siendo ese id exacto en vuestra base de datos.
- Que `ir.attachment` tenga de verdad los campos `is_knowledge_document` /
  `body_markdown` con `rms_custom_knowledge` instalado (no se pudo instalar
  ese módulo aquí porque depende de `document_knowledge`, que no está en
  este repositorio).
