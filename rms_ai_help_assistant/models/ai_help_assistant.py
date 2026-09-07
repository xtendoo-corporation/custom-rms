# -*- coding: utf-8 -*-

import json
import logging

import requests

from odoo import api, models

_logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MAX_TOOL_ROUNDS = 6  # una consulta puede necesitar varias herramientas encadenadas
                     # (p. ej. buscar_cliente -> consultar_producto -> consultar_precio_cliente)
LLM_TIMEOUT = 60
SEARCH_LIMIT = 8

# ---------------------------------------------------------------------------
# IMPORTANTE — por qué este módulo es seguro de instalar tal cual:
#
# 1. Nunca usa sudo(). Todas las búsquedas se hacen con self.env (el usuario
#    que pregunta), así que los permisos de acceso y las reglas de registro
#    (ir.model.access, ir.rule) que ya tenéis configuradas en Odoo se aplican
#    exactamente igual que si el usuario navegara la interfaz a mano. No hace
#    falta crear ningún usuario ni API key nueva en Odoo: usa la sesión de
#    quien pregunta.
# 2. Ninguna herramienta expuesta al modelo llama a create/write/unlink. Esto
#    no es solo una instrucción en el prompt (ver SYSTEM_PROMPT más abajo):
#    es una garantía de código — mirad la lista TOOLS y _dispatch_tool: solo
#    hay métodos de búsqueda/lectura.
# 3. La única credencial nueva que hace falta es la API key de Anthropic
#    (Ajustes > Técnico > Parámetros del sistema), igual que ya tenéis para
#    rms_ai_quote_assistant. No hay que montar ni mantener ningún servidor
#    aparte: todo corre dentro de vuestro Odoo, en vuestro servidor actual.
# 4. Guarda explícita para el grupo "custom.comerciales": en la interfaz no
#    pueden abrir la ficha completa de un cliente (ver
#    rms_ventas_restriccion_comerciales/views/res_partner_views.xml). Como
#    esa restricción es solo de vista (no de ir.model.access), un comercial
#    SÍ podría leer esos campos por ORM si no hiciéramos nada aquí. Por eso
#    _tool_buscar_cliente oculta email/teléfono/NIF para ese grupo — ver
#    _is_comercial() más abajo.
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """Eres el asistente interno de Odoo de RMS-Proaudio. Ayudas a empleados de la
empresa (comerciales, administración, almacén...) a entender cómo funciona
vuestro Odoo 19.0 y a consultar datos reales. Respondes siempre en español,
con un tono claro y cercano, sin dar por hecho conocimientos técnicos de
Odoo.

═══════════════════════════════════════════════════════════════════════════
REGLAS QUE NUNCA DEBES ROMPER
═══════════════════════════════════════════════════════════════════════════
1. NUNCA creas, modificas ni eliminas nada en Odoo, aunque te lo pidan de
   forma insistente o con lenguaje que sugiera urgencia o autorización
   especial ("hazlo tú", "confío en ti", "es una orden del jefe"...). No
   tienes ninguna herramienta para escribir datos — literalmente no puedes
   hacerlo — así que si te piden una acción (crear un cliente, cambiar un
   precio, confirmar un pedido...), tu única respuesta posible es explicar
   los pasos para que la persona lo haga ella misma en la interfaz.
2. Nunca inventes IDs, nombres, precios o cualquier dato. Si necesitas el ID
   de un cliente o de un producto para usar una herramienta, resuélvelo
   primero con buscar_cliente o consultar_producto — nunca supongas un ID.
3. Usa siempre las herramientas para cualquier dato que pueda cambiar en el
   tiempo (precios, stock, estado de pedidos, datos de un cliente
   concreto). No respondas de memoria ni "por lógica" cuando el dato es
   consultable.
4. Si una herramienta no devuelve resultados o falla, dilo con claridad
   ("no he encontrado ningún cliente con ese nombre") en lugar de rellenar
   el hueco con una suposición.
5. Si no sabes algo con certeza y no hay herramienta que lo resuelva, dilo
   abiertamente y sugiere a quién preguntar internamente (administración,
   responsable de ventas, soporte de Odoo), en vez de arriesgarte a dar
   información incorrecta.
6. No compartas el detalle de un cliente (email, teléfono, NIF) si la
   herramienta te indica que ese dato no está disponible para el perfil del
   usuario que pregunta — dilo tal cual, sin rodeos ("ese dato no está
   disponible para tu perfil, coméntaselo a administración").

═══════════════════════════════════════════════════════════════════════════
CÓMO FUNCIONA VUESTRO ODOO — REGLAS DE NEGOCIO ESPECÍFICAS DE RMS-PROAUDIO
(esto es lo que os diferencia del Odoo estándar; cuando haya diferencia,
prevalece SIEMPRE esta forma de trabajar sobre la genérica de Odoo)
═══════════════════════════════════════════════════════════════════════════

— CLIENTES Y CONTACTOS —
- Un contacto (empresa o persona) puede tener varios "roles" a la vez
  mediante contactos hijos marcados con roles: facturación, dirección de
  entrega, listas de precios, técnicos, comunicación general. No hace falta
  crear un contacto distinto por cada dirección: se gestiona con estos
  roles desde la ficha del cliente (pestaña de contactos/direcciones).
- Al importar contactos desde Excel/CSV (importación nativa de Odoo), la
  validación de NIF/CIF está desactivada a propósito: se pueden importar
  aunque el NIF no sea válido según el validador estándar. Al crear un
  cliente a mano desde el formulario, esa validación SÍ se aplica con
  normalidad.
- Los usuarios del grupo "Comerciales" ven los listados de clientes y
  productos con normalidad, pero no pueden abrir la ficha completa (ni de
  cliente ni de producto) para ver el detalle — verán un aviso de permiso
  denegado si lo intentan. Si necesitan ver o cambiar algo del detalle,
  deben pedírselo a administración o al responsable de ventas.

— LISTAS DE PRECIOS Y DESCUENTOS —
- Cada línea de una lista de precios puede tener hasta TRES descuentos
  encadenados (descuento 1, 2 y 3), no uno solo. Se aplican en cascada, no
  sumados: por ejemplo, 10% + 10% no es un 20% de descuento total, es un
  19% (0,9 × 0,9 = 0,81 → 19% de descuento acumulado).
- La lista de precios de un presupuesto se calcula automáticamente a partir
  del cliente (su lista de precios asignada en su ficha). Los comerciales
  pueden VER la lista de precios aplicada en un presupuesto pero no pueden
  cambiarla desde ahí: si un presupuesto necesita otra lista de precios,
  tiene que cambiarla alguien que no sea del grupo Comerciales.

— ESTADOS DE PRODUCTO —
Cada producto (y cada número de serie/lote concreto) tiene un estado:
Nuevo, Demo, Ex-Demo, 2ª Mano o Descontinuado. Esto afecta directamente a
si se puede vender y a qué precio:
- Demo: NO se puede presupuestar ni vender. Si alguien intenta añadirlo a
  un presupuesto, Odoo lo bloqueará con un error.
- Ex-Demo y 2ª Mano: cuando se vende un número de serie/lote concreto en
  este estado, el precio no sale de la tarifa general sino de un precio
  específico fijado en ese número de serie/lote ("Precio Custom").
- 2ª Mano recibe además, automáticamente, un 10% de descuento adicional.
- Descontinuado: precio 0 si se referencia por lote en un pedido (se
  entiende como liquidación), y el producto se archiva automáticamente en
  cuanto su stock llega a 0 (proceso automático nocturno).

— STOCK Y CESIONES —
- Además de las salidas de venta normales, existe un proceso de "Cesión de
  Mercancía" (Cesiones de Stock) para registrar mercancía que se cede a un
  cliente o a una ubicación externa sin ser una venta (por ejemplo,
  material en depósito o préstamo). Al confirmar una cesión se genera y
  valida automáticamente un movimiento de stock (albarán) que descuenta la
  mercancía del almacén de origen.

— PRESUPUESTOS Y PEDIDOS —
- Los responsables de cada categoría de producto se suscriben
  automáticamente como seguidores de cualquier presupuesto que incluya un
  producto de su categoría (para que se enteren sin tener que ir buscando).
- Existe una plantilla de impresión de presupuesto personalizada (formato
  propio de RMS-Proaudio), distinta de la plantilla estándar de Odoo.
- También hay asistentes (wizards) para importar productos y presupuestos
  completos desde Excel, con resolución automática de variantes y cálculo
  de descuentos.

— COMUNICACIONES —
- El botón "Enviar mensaje" del chatter está oculto a propósito: la forma
  de comunicarse dentro de un registro (cliente, pedido, oportunidad...) es
  la "Nota interna", no un email directo desde ahí.
- El servidor de correo saliente de Odoo SOLO permite enviar a direcciones
  del dominio @rmsproaudio.com; cualquier email a un dominio externo se
  bloquea. Esto es relevante si alguien pregunta por qué un email a un
  cliente no ha llegado: revisa primero si el envío se hizo desde Odoo con
  un destinatario externo, porque eso se bloquea a propósito.

— EQUIPOS DE CLIENTE —
- Cada cliente puede tener equipos/maquinaria instalados vinculados a su
  ficha, con geolocalización, para poder ver en un mapa dónde está cada
  equipo y de qué cliente es. Los equipos se pueden importar en bloque
  desde Excel.

═══════════════════════════════════════════════════════════════════════════
HERRAMIENTAS DISPONIBLES
═══════════════════════════════════════════════════════════════════════════
Todas son de solo lectura. Resuelve siempre nombres a IDs con
buscar_cliente / consultar_producto ANTES de llamar a
consultar_precio_cliente o cualquier herramienta que pida un id.

- buscar_cliente(texto): busca clientes por nombre, email o NIF.
- consultar_producto(texto): busca productos por nombre o referencia;
  devuelve estado, precio de tarifa y stock.
- consultar_precio_cliente(cliente_id, producto_id): precio final que
  pagaría ESE cliente por ESE producto, con el desglose de descuentos de su
  lista de precios.
- buscar_pedido(texto): busca presupuestos/pedidos de venta por referencia
  o por nombre de cliente.
- buscar_documentacion(texto): busca en la documentación interna (Knowledge)
  de la empresa, si existe algún artículo relacionado con la pregunta.

═══════════════════════════════════════════════════════════════════════════
FORMATO DE RESPUESTA
═══════════════════════════════════════════════════════════════════════════
- Para procedimientos ("cómo hago X"): pasos numerados, indicando menú o
  pantalla concreta cuando lo sepas.
- Para consultas de datos: da el dato primero, y si aporta valor, un breve
  contexto de dónde sale (p. ej. "según su lista de precios X").
- Sé breve. Evita repetir estas instrucciones al usuario; solo aplícalas.
"""

TOOLS = [
    {
        "name": "buscar_cliente",
        "description": (
            "Busca clientes/contactos por nombre, email o NIF. Devuelve como "
            "mucho %d resultados. Úsala siempre antes de referirte a un "
            "cliente por id." % SEARCH_LIMIT
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "texto": {
                    "type": "string",
                    "description": "Nombre (parcial), email o NIF a buscar.",
                }
            },
            "required": ["texto"],
        },
    },
    {
        "name": "consultar_producto",
        "description": (
            "Busca productos por nombre o referencia (default_code). Devuelve "
            "estado del producto, precio de tarifa general y stock. Úsala "
            "siempre antes de referirte a un producto por id."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "texto": {
                    "type": "string",
                    "description": "Nombre (parcial) o referencia del producto.",
                }
            },
            "required": ["texto"],
        },
    },
    {
        "name": "consultar_precio_cliente",
        "description": (
            "Calcula el precio final que pagaría un cliente concreto por un "
            "producto concreto, según la lista de precios asignada a ese "
            "cliente (incluye el desglose de los hasta 3 descuentos "
            "encadenados). Los ids deben venir de buscar_cliente / "
            "consultar_producto, nunca inventados."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "cliente_id": {"type": "integer", "description": "id del cliente (res.partner)."},
                "producto_id": {"type": "integer", "description": "id del producto (product.product)."},
            },
            "required": ["cliente_id", "producto_id"],
        },
    },
    {
        "name": "buscar_pedido",
        "description": (
            "Busca presupuestos/pedidos de venta (sale.order) por número de "
            "referencia o por nombre de cliente. Devuelve estado y total."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "texto": {
                    "type": "string",
                    "description": "Referencia del pedido (p. ej. 'S00123') o nombre de cliente.",
                }
            },
            "required": ["texto"],
        },
    },
    {
        "name": "buscar_documentacion",
        "description": (
            "Busca en la documentación interna de la empresa (app Knowledge) "
            "artículos relacionados con la pregunta. Úsala cuando la duda "
            "parezca cubierta por un procedimiento documentado internamente."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "texto": {
                    "type": "string",
                    "description": "Términos de búsqueda.",
                }
            },
            "required": ["texto"],
        },
    },
]


class RmsAiHelpAssistant(models.AbstractModel):
    _name = "rms.ai.help.assistant"
    _description = "RMS AI Help Assistant"

    # ------------------------------------------------------------------
    # Punto de entrada RPC (llamado desde el chat OWL vía this.orm.call)
    # ------------------------------------------------------------------

    @api.model
    def send_message(self, messages):
        """messages: [{'role': 'user'|'assistant', 'text': str}, ...] —
        transcripción visible completa hasta ahora. Sin estado en servidor:
        el cliente reenvía toda la conversación en cada turno.

        Devuelve siempre uno de:
          {'type': 'message', 'text': ...}
          {'type': 'error', 'text': ...}
        (a diferencia de rms_ai_quote_assistant, no existe {'type':
        'proposal', ...}: este asistente nunca propone ni crea nada, solo
        informa.)
        """
        api_key = self._get_api_key()
        if not api_key:
            return {
                "type": "error",
                "text": (
                    "Falta configurar la clave de la API de Anthropic. "
                    "Ajustes > Técnico > Parámetros del sistema > "
                    "rms_ai_help_assistant.anthropic_api_key"
                ),
            }
        return self._run_anthropic_loop(api_key, self._get_model(), messages)

    def _run_anthropic_loop(self, api_key, model, messages):
        system = [
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ]
        anthropic_messages = [
            {"role": m["role"], "content": m["text"]} for m in messages
        ]

        for _round in range(MAX_TOOL_ROUNDS):
            try:
                response = self._call_anthropic(
                    api_key, model, system, anthropic_messages, TOOLS
                )
            except Exception:
                _logger.exception("Error llamando a la API de Anthropic")
                return {
                    "type": "error",
                    "text": "No se pudo contactar con el servicio de IA. Inténtalo de nuevo.",
                }

            usage = response.get("usage") or {}
            _logger.info(
                "Anthropic usage: input=%s cache_read=%s cache_creation=%s output=%s",
                usage.get("input_tokens"), usage.get("cache_read_input_tokens"),
                usage.get("cache_creation_input_tokens"), usage.get("output_tokens"),
            )

            content_blocks = response.get("content", [])
            tool_use_blocks = [b for b in content_blocks if b.get("type") == "tool_use"]
            text_blocks = [b["text"] for b in content_blocks if b.get("type") == "text"]

            if not tool_use_blocks:
                if text_blocks:
                    return {"type": "message", "text": " ".join(text_blocks)}
                _logger.warning(
                    "Respuesta de Anthropic sin texto ni tool_use (stop_reason=%s): %s",
                    response.get("stop_reason"), content_blocks,
                )
                continue

            # Ejecutamos TODAS las herramientas solicitadas en este turno
            # (Claude puede pedir varias en paralelo) y devolvemos sus
            # resultados juntos, como exige la API de tool use.
            anthropic_messages.append({"role": "assistant", "content": content_blocks})
            tool_results = []
            for block in tool_use_blocks:
                result_json = self._dispatch_tool(block["name"], block.get("input") or {})
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block["id"],
                        "content": result_json,
                    }
                )
            anthropic_messages.append({"role": "user", "content": tool_results})

        return {
            "type": "message",
            "text": (
                "No he podido completar tu consulta con la información "
                "disponible. ¿Puedes darme más detalles?"
            ),
        }

    # ------------------------------------------------------------------
    # Despacho de herramientas — SOLO LECTURA. Cada método usa self.env
    # (permisos del usuario que pregunta), nunca sudo(). Ninguno de estos
    # métodos escribe en Odoo: no hay create/write/unlink en todo el
    # fichero.
    # ------------------------------------------------------------------

    def _dispatch_tool(self, name, tool_input):
        handler = {
            "buscar_cliente": self._tool_buscar_cliente,
            "consultar_producto": self._tool_consultar_producto,
            "consultar_precio_cliente": self._tool_consultar_precio_cliente,
            "buscar_pedido": self._tool_buscar_pedido,
            "buscar_documentacion": self._tool_buscar_documentacion,
        }.get(name)
        if not handler:
            return json.dumps({"error": "Herramienta desconocida: %s" % name}, ensure_ascii=False)
        try:
            return json.dumps(handler(tool_input), ensure_ascii=False)
        except Exception as exc:
            _logger.exception("Error ejecutando la herramienta %s", name)
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

    def _is_comercial(self):
        # has_group ya maneja con gracia el caso de que el external id no
        # exista (devuelve False), así que no hace falta try/except aquí.
        # 'custom.comerciales' es el external id real usado en
        # rms_ventas_restriccion_comerciales/views/*.xml en producción; no
        # está definido como <record model="res.groups"> en ningún módulo
        # de este repositorio, así que se asume creado manualmente en la
        # base de datos (Ajustes > Técnico > Grupos).
        return self.env.user.has_group("custom.comerciales")

    def _tool_buscar_cliente(self, tool_input):
        texto = (tool_input.get("texto") or "").strip()
        if not texto:
            return {"error": "Falta el texto a buscar."}
        domain = [
            "|", "|",
            ("name", "ilike", texto),
            ("email", "ilike", texto),
            ("vat", "ilike", texto),
        ]
        partners = self.env["res.partner"].search(domain, limit=SEARCH_LIMIT)
        oculto_para_comerciales = self._is_comercial()
        results = []
        for p in partners:
            row = {
                "id": p.id,
                "nombre": p.display_name,
                "es_empresa": p.is_company,
                "ciudad": p.city or "",
                "comercial_asignado": p.user_id.name or "",
                "lista_precios": p.property_product_pricelist.name or "",
            }
            if oculto_para_comerciales:
                row["nota"] = (
                    "Email, teléfono y NIF no disponibles para tu perfil "
                    "(grupo Comerciales); pídeselos a administración."
                )
            else:
                row["email"] = p.email or ""
                row["telefono"] = p.phone or ""
                row["nif"] = p.vat or ""
            results.append(row)
        return {"resultados": results, "total_encontrado": len(results)}

    def _tool_consultar_producto(self, tool_input):
        texto = (tool_input.get("texto") or "").strip()
        if not texto:
            return {"error": "Falta el texto a buscar."}
        domain = ["|", ("name", "ilike", texto), ("default_code", "ilike", texto)]
        products = self.env["product.product"].search(domain, limit=SEARCH_LIMIT)
        results = []
        for prod in products:
            state = prod.product_tmpl_id.product_state_id
            results.append(
                {
                    "id": prod.id,
                    "referencia": prod.default_code or "",
                    "nombre": prod.display_name,
                    "estado": state.name if state else "",
                    "estado_codigo": state.code if state else "",
                    "precio_tarifa": prod.list_price,
                    "stock_disponible": prod.qty_available,
                    "stock_previsto": prod.virtual_available,
                }
            )
        return {"resultados": results, "total_encontrado": len(results)}

    def _tool_consultar_precio_cliente(self, tool_input):
        partner_id = tool_input.get("cliente_id")
        product_id = tool_input.get("producto_id")
        partner = self.env["res.partner"].browse(partner_id).exists()
        if not partner:
            return {"error": "No existe ningún cliente con id %s. Busca primero con buscar_cliente." % partner_id}
        product = self.env["product.product"].browse(product_id).exists()
        if not product:
            return {"error": "No existe ningún producto con id %s. Busca primero con consultar_producto." % product_id}

        pricelist = partner.property_product_pricelist
        if not pricelist:
            return {
                "cliente": partner.display_name,
                "producto": product.display_name,
                "lista_precios": "",
                "precio_final": product.list_price,
                "nota": "El cliente no tiene lista de precios asignada; se muestra el precio de tarifa general.",
            }

        try:
            precio_final = pricelist._get_product_price(product, 1.0)
        except Exception:
            _logger.exception("No se pudo calcular el precio con _get_product_price")
            precio_final = product.list_price

        descuentos = None
        try:
            rule_id = pricelist._get_product_rule(product, 1.0)
            if rule_id:
                item = self.env["product.pricelist.item"].browse(rule_id)
                if hasattr(item, "discount1"):
                    descuentos = {
                        "descuento_1": item.discount1,
                        "descuento_2": getattr(item, "discount2", 0.0),
                        "descuento_3": getattr(item, "discount3", 0.0),
                    }
        except Exception:
            # No crítico: si no podemos obtener el desglose, devolvemos igualmente el precio final.
            _logger.exception("No se pudo obtener el desglose de descuentos de la tarifa")

        result = {
            "cliente": partner.display_name,
            "producto": product.display_name,
            "lista_precios": pricelist.name,
            "precio_tarifa_general": product.list_price,
            "precio_final": precio_final,
        }
        if descuentos:
            result["descuentos_encadenados"] = descuentos
        state = product.product_tmpl_id.product_state_id
        if state and state.code in ("demo",):
            result["aviso"] = "Este producto está en estado Demo: no se puede presupuestar ni vender."
        elif state and state.code == "discontinued":
            result["aviso"] = "Este producto está Descontinuado."
        return result

    def _tool_buscar_pedido(self, tool_input):
        texto = (tool_input.get("texto") or "").strip()
        if not texto:
            return {"error": "Falta el texto a buscar."}
        domain = ["|", ("name", "ilike", texto), ("partner_id.name", "ilike", texto)]
        orders = self.env["sale.order"].search(domain, limit=SEARCH_LIMIT, order="date_order desc")
        state_labels = dict(orders._fields["state"].selection) if orders else {}
        results = []
        for order in orders:
            results.append(
                {
                    "id": order.id,
                    "referencia": order.name,
                    "cliente": order.partner_id.display_name,
                    "estado": state_labels.get(order.state, order.state),
                    "total": order.amount_total,
                    "fecha": order.date_order and order.date_order.strftime("%d/%m/%Y") or "",
                }
            )
        return {"resultados": results, "total_encontrado": len(results)}

    def _tool_buscar_documentacion(self, tool_input):
        texto = (tool_input.get("texto") or "").strip()
        if not texto:
            return {"error": "Falta el texto a buscar."}
        Attachment = self.env["ir.attachment"]
        if "is_knowledge_document" not in Attachment._fields:
            return {"error": "El módulo de documentación interna (rms_custom_knowledge) no está instalado."}
        domain = [
            ("is_knowledge_document", "=", True),
            "|", ("name", "ilike", texto), ("body_markdown", "ilike", texto),
        ]
        docs = Attachment.search(domain, limit=5)
        results = []
        for doc in docs:
            extracto = (doc.body_markdown or "")[:800]
            results.append(
                {
                    "titulo": doc.name,
                    "carpeta": doc.knowledge_category_id.complete_name or "",
                    "extracto": extracto,
                }
            )
        return {"resultados": results, "total_encontrado": len(results)}

    # ------------------------------------------------------------------
    # Configuración + HTTP
    # ------------------------------------------------------------------

    def _get_api_key(self):
        ICP = self.env["ir.config_parameter"].sudo()
        # Config propia del módulo; si no está puesta, cae de forma
        # opcional en la misma clave que uséis para rms_ai_quote_assistant
        # (para no tener que configurarla dos veces). No crea ninguna
        # dependencia entre módulos: ir.config_parameter es una tabla
        # global, simplemente reutiliza el valor si existe.
        return ICP.get_param("rms_ai_help_assistant.anthropic_api_key") or ICP.get_param(
            "rms_ai_quote_assistant.anthropic_api_key"
        )

    def _get_model(self):
        return self.env["ir.config_parameter"].sudo().get_param(
            "rms_ai_help_assistant.anthropic_model", "claude-sonnet-5"
        )

    def _get_anthropic_workspace_id(self):
        # Solo hace falta para API keys "identity-linked" (creadas dentro de
        # una organización/workspace de la consola de Anthropic). Las claves
        # personales normales no lo necesitan.
        ICP = self.env["ir.config_parameter"].sudo()
        return ICP.get_param("rms_ai_help_assistant.anthropic_workspace_id") or ICP.get_param(
            "rms_ai_quote_assistant.anthropic_workspace_id"
        )

    def _call_anthropic(self, api_key, model, system, messages, tools):
        payload = {
            "model": model,
            "max_tokens": 4096,
            "system": system,
            "messages": messages,
            "tools": tools,
        }
        headers = {
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        workspace_id = self._get_anthropic_workspace_id()
        if workspace_id:
            headers["anthropic-workspace-id"] = workspace_id
        response = requests.post(
            ANTHROPIC_API_URL,
            headers=headers,
            json=payload,
            timeout=LLM_TIMEOUT,
        )
        if not response.ok:
            _logger.error("Anthropic API error %s: %s", response.status_code, response.text[:2000])
        response.raise_for_status()
        return response.json()
