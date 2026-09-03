# -*- coding: utf-8 -*-

import json
import logging

import requests

from odoo import api, models

_logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MAX_TOOL_ROUNDS = 5
ANTHROPIC_TIMEOUT = 30

SYSTEM_PROMPT = """Eres el asistente de presupuestos de RMS Proaudio. Ayudas a un comercial a
crear un presupuesto (sale.order) en Odoo a partir de una instrucción en
lenguaje natural, por ejemplo: "hazle un presupuesto a fulanito con 3 X40 y
una Quantum 3".

Dispones de estas herramientas:
- search_partners(query): busca clientes por nombre o email (coincidencia
  aproximada). Úsala para resolver el cliente mencionado.
- search_products(query): busca productos por referencia interna
  (default_code) o nombre (coincidencia aproximada). Úsala para resolver
  cada artículo mencionado.
- propose_quote(partner_id, lines): entrega la propuesta final (cliente +
  líneas resueltas) para que el usuario la confirme. Esta herramienta NO
  crea nada todavía. Es la ÚNICA forma que tienes de terminar tu trabajo
  cuando cliente y líneas están resueltos sin ambigüedad. No tienes ninguna
  herramienta para crear el presupuesto directamente: eso lo hace el
  sistema, solo después de que el usuario confirme explícitamente en la
  interfaz.

Sigue este flujo obligatorio:
1. Extrae del mensaje del usuario el nombre aproximado del cliente y la
   lista de artículos con sus cantidades.
2. Usa search_partners para resolver el cliente (nombre comercial vs razón
   social, abreviaturas, con/sin acentos).
3. Usa search_products para resolver cada artículo (abreviaturas,
   referencias parciales, mayúsculas/tildes/erratas — p. ej. "X 40" puede
   corresponder a "ULTRA-X40,EU,110,STD,3PIN").
4. Si una búsqueda no da resultado razonable, o da varios candidatos
   igual de plausibles, NO asumas: responde con texto normal preguntando
   al usuario que aclare, y espera su respuesta.
5. Nunca inventes un id, default_code o nombre: usa exclusivamente lo que
   devuelvan search_partners/search_products.
6. Cuando cliente y TODAS las líneas estén resueltos sin ambigüedad, llama
   a propose_quote con partner_id y las líneas (product_id + quantity).
7. Si el usuario pide cambiar la tarifa/lista de precios, indica que no se
   puede desde el chat: se aplica automáticamente la tarifa del cliente.
8. Responde siempre en español, breve y claro."""

SEARCH_PARTNERS_TOOL = {
    "name": "search_partners",
    "description": (
        "Busca clientes (res.partner) por nombre o email usando coincidencia "
        "aproximada. Devuelve hasta 10 candidatos con id, nombre y email. "
        "Úsala para resolver el cliente mencionado. Nunca inventes un "
        "partner_id: usa solo los que devuelva esta herramienta."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Nombre completo o parcial del cliente, o su email.",
            }
        },
        "required": ["query"],
    },
}

SEARCH_PRODUCTS_TOOL = {
    "name": "search_products",
    "description": (
        "Busca productos (product.product) por referencia interna "
        "(default_code) exacta o, si no hay coincidencia, por nombre "
        "(aproximada). Devuelve hasta 10 candidatos con id, nombre y "
        "default_code. Úsala para resolver cada artículo mencionado. Nunca "
        "inventes un product_id ni un default_code: usa solo los que "
        "devuelva esta herramienta."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Referencia interna (default_code) o nombre/descripción parcial del producto.",
            }
        },
        "required": ["query"],
    },
}

PROPOSE_QUOTE_TOOL = {
    "name": "propose_quote",
    "description": (
        "Entrega la propuesta final de presupuesto (cliente + líneas) para "
        "que el usuario la revise y confirme. NO crea ningún registro en "
        "Odoo — es la única forma que tienes de terminar tu trabajo. Llama "
        "a esta herramienta solo cuando el cliente y TODAS las líneas estén "
        "resueltos sin ambigüedad mediante search_partners y search_products."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "partner_id": {
                "type": "integer",
                "description": "id del cliente resuelto, obtenido de search_partners.",
            },
            "lines": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "product_id": {
                            "type": "integer",
                            "description": "id del producto resuelto, obtenido de search_products.",
                        },
                        "quantity": {
                            "type": "number",
                            "description": "cantidad solicitada.",
                        },
                    },
                    "required": ["product_id", "quantity"],
                },
            },
        },
        "required": ["partner_id", "lines"],
    },
}


class RmsAiQuoteAssistant(models.AbstractModel):
    _name = "rms.ai.quote.assistant"
    _description = "RMS AI Quote Assistant"

    # ---------------------------------------------------------------------
    # Public RPC entry points (called via this.orm.call from the OWL chat)
    # ---------------------------------------------------------------------

    @api.model
    def send_message(self, messages):
        """messages: [{'role': 'user'|'assistant', 'text': str}, ...] — the
        full visible chat transcript so far, ending with the latest user
        message. Stateless: the caller resends the whole transcript every
        time. Runs the Claude tool-use loop entirely server-side, under the
        calling user's own permissions (no sudo on any business model).

        Returns one of:
          {'type': 'message', 'text': ...}
          {'type': 'proposal', 'text': ..., 'partner_id': int, 'lines': [...]}
          {'type': 'error', 'text': ...}
        """
        api_key = self._get_api_key()
        if not api_key:
            return {
                "type": "error",
                "text": (
                    "Falta configurar la clave de la API de Anthropic. "
                    "Ajustes > Técnico > Parámetros del sistema > "
                    "rms_ai_quote_assistant.anthropic_api_key"
                ),
            }
        model = self._get_model()
        anthropic_messages = [
            {"role": m["role"], "content": m["text"]} for m in messages
        ]
        tools = [SEARCH_PARTNERS_TOOL, SEARCH_PRODUCTS_TOOL, PROPOSE_QUOTE_TOOL]

        for _round in range(MAX_TOOL_ROUNDS):
            try:
                response = self._call_anthropic(
                    api_key, model, SYSTEM_PROMPT, anthropic_messages, tools
                )
            except Exception:
                _logger.exception("Error llamando a la API de Anthropic")
                return {
                    "type": "error",
                    "text": "No se pudo contactar con el servicio de IA. Inténtalo de nuevo.",
                }

            content_blocks = response.get("content", [])
            tool_use_blocks = [b for b in content_blocks if b.get("type") == "tool_use"]
            text_blocks = [b["text"] for b in content_blocks if b.get("type") == "text"]

            propose_block = next(
                (b for b in tool_use_blocks if b["name"] == "propose_quote"), None
            )
            if propose_block:
                try:
                    preview = self._build_quote_preview(
                        propose_block["input"]["partner_id"],
                        propose_block["input"]["lines"],
                    )
                except ValueError as exc:
                    anthropic_messages.append(
                        {"role": "assistant", "content": content_blocks}
                    )
                    anthropic_messages.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": propose_block["id"],
                                    "content": str(exc),
                                    "is_error": True,
                                }
                            ],
                        }
                    )
                    continue
                return {
                    "type": "proposal",
                    "text": self._format_preview_text(preview),
                    "partner_id": preview["partner_id"],
                    "lines": preview["lines"],
                }

            if not tool_use_blocks:
                return {
                    "type": "message",
                    "text": " ".join(text_blocks) or "(el asistente no ha devuelto respuesta)",
                }

            anthropic_messages.append({"role": "assistant", "content": content_blocks})
            tool_results = []
            for block in tool_use_blocks:
                if block["name"] == "search_partners":
                    result = self._tool_search_partners(block["input"]["query"])
                elif block["name"] == "search_products":
                    result = self._tool_search_products(block["input"]["query"])
                else:
                    result = {"error": "Herramienta desconocida: %s" % block["name"]}
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block["id"],
                        "content": json.dumps(result),
                    }
                )
            anthropic_messages.append({"role": "user", "content": tool_results})

        return {
            "type": "message",
            "text": (
                "No he podido resolver la petición. ¿Puedes darme más "
                "detalles sobre el cliente o los productos exactos?"
            ),
        }

    @api.model
    def confirm_quote(self, partner_id, lines):
        """Deterministic, non-LLM creation of exactly one sale.order, called
        only when the user clicks "Confirmar" on a previously shown
        proposal. lines: [{'product_id': int, 'quantity': float}, ...]
        """
        try:
            preview = self._build_quote_preview(partner_id, lines)
        except ValueError as exc:
            return {"type": "error", "text": str(exc)}

        partner = self.env["res.partner"].browse(partner_id)
        order_vals = {
            "partner_id": partner.id,
            "order_line": [
                (0, 0, {"product_id": l["product_id"], "product_uom_qty": l["quantity"]})
                for l in lines
            ],
        }
        # Pricelist guard: never taken from the LLM or from any request
        # parameter — always the partner's own pricelist. See
        # rms_ventas_restriccion_comerciales/views/sale_order_views.xml for
        # the UI-level counterpart of this restriction (readonly field for
        # the custom.comerciales group); that protection doesn't apply here
        # since this tool bypasses the form view entirely, so it's
        # unconditional here for every user, not just comerciales.
        if partner.property_product_pricelist:
            order_vals["pricelist_id"] = partner.property_product_pricelist.id

        try:
            order = self.env["sale.order"].create(order_vals)
        except Exception as exc:
            _logger.exception("Error creando presupuesto desde el asistente IA")
            return {"type": "error", "text": "No se pudo crear el presupuesto: %s" % exc}

        return {
            "type": "result",
            "text": "Presupuesto creado: %s (id=%s) - Total: %s"
            % (order.name, order.id, order.amount_total),
            "order_id": order.id,
            "order_name": order.name,
            "amount_total": order.amount_total,
        }

    # ---------------------------------------------------------------------
    # Tool implementations — run under self.env, i.e. the calling user's own
    # permissions and record rules (never sudo).
    # ---------------------------------------------------------------------

    def _tool_search_partners(self, query):
        partners = self.env["res.partner"].search_read(
            ["|", ("name", "ilike", query), ("email", "ilike", query)],
            ["id", "name", "email"],
            limit=10,
            order="name",
        )
        return {"candidates": partners}

    def _tool_search_products(self, query):
        Product = self.env["product.product"]
        products = Product.search_read(
            [("default_code", "=", query)], ["id", "name", "default_code"], limit=10
        )
        if not products:
            products = Product.search_read(
                [("name", "ilike", query)], ["id", "name", "default_code"], limit=10
            )
        return {"candidates": products}

    def _build_quote_preview(self, partner_id, lines):
        partner = self.env["res.partner"].browse(partner_id).exists()
        if not partner:
            raise ValueError("No existe ningún cliente con id %s." % partner_id)
        if not lines:
            raise ValueError("No hay ninguna línea de producto que proponer.")
        Product = self.env["product.product"]
        line_previews = []
        for line in lines:
            product = Product.browse(line["product_id"]).exists()
            if not product:
                raise ValueError("No existe ningún producto con id %s." % line["product_id"])
            line_previews.append(
                {
                    "product_id": product.id,
                    "name": product.display_name,
                    "default_code": product.default_code or "",
                    "quantity": line["quantity"],
                }
            )
        return {
            "partner_id": partner.id,
            "partner_name": partner.name,
            "partner_email": partner.email or "",
            "lines": line_previews,
        }

    def _format_preview_text(self, preview):
        lines_txt = "\n".join(
            "- %s x %s (%s)" % (l["quantity"], l["name"], l["default_code"])
            for l in preview["lines"]
        )
        return (
            "Cliente: %s (%s)\n%s\n\n¿Confirmas la creación de este presupuesto?"
            % (preview["partner_name"], preview["partner_email"], lines_txt)
        )

    # ---------------------------------------------------------------------
    # Config + HTTP
    # ---------------------------------------------------------------------

    def _get_api_key(self):
        return self.env["ir.config_parameter"].sudo().get_param(
            "rms_ai_quote_assistant.anthropic_api_key"
        )

    def _get_model(self):
        return self.env["ir.config_parameter"].sudo().get_param(
            "rms_ai_quote_assistant.anthropic_model", "claude-sonnet-5"
        )

    def _call_anthropic(self, api_key, model, system, messages, tools):
        payload = {
            "model": model,
            "max_tokens": 1024,
            "system": system,
            "messages": messages,
            "tools": tools,
        }
        response = requests.post(
            ANTHROPIC_API_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            json=payload,
            timeout=ANTHROPIC_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()
