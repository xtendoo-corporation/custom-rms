# -*- coding: utf-8 -*-

import json
import logging

import requests

from odoo import api, models

_logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
GEMINI_API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
MAX_TOOL_ROUNDS = 3
LLM_TIMEOUT = 60

# The model is given the full accessible partner/product catalog inline in
# the system prompt (mirroring list_partners.py --all / list_products.py
# --all from the original ia-presupuestos toolkit) instead of parameterized
# search tools. A plain ILIKE search tool cannot bridge natural-language/
# colloquial references (e.g. "Panther L" -> "PANTHER-L,80,W/P,3P-XLR,MEP,
# PWRCON TOP", or "Quantum 2" -> a DiGiCo Quantum225 console by industry
# naming convention) the way the model's own world knowledge can when it
# can see the whole catalog at once. This trades tool-call round-trips for
# a larger prompt (the full catalog is a few thousand records, comfortably
# within both providers' context windows, but re-sent on every turn since
# the design is stateless — a known cost/latency trade-off, accepted
# because it's what the original toolkit did and what makes free-text
# resolution actually work).
SYSTEM_PROMPT_INTRO = """Eres el asistente de presupuestos de RMS Proaudio. Ayudas a un comercial a
crear un presupuesto (sale.order) en Odoo a partir de una instrucción en
lenguaje natural, por ejemplo: "hazle un presupuesto a fulanito con 3 X40 y
una Quantum 3".

Más abajo tienes el listado COMPLETO de clientes y de productos a los que
tienes acceso (en JSON). Resuelve el cliente y cada artículo mencionado por
coincidencia semántica contra esos datos: nombre comercial vs. razón
social, abreviaturas, con/sin acentos, erratas, y nomenclatura habitual del
sector aunque no coincida literalmente (p. ej. "Panther L" puede
corresponder a un producto llamado "PANTHER-L,80,W/P,3P-XLR,MEP,PWRCON
TOP", o "Quantum 2" a una consola DiGiCo Quantum225 por ser su nombre
coloquial habitual, aunque el texto "Quantum 2" no aparezca literalmente).

Dispones de dos herramientas:
- list_available_serials(product_id): devuelve el listado real de números
  de serie disponibles (2ª Mano/Ex-Demo, ya descontando lo reservado en
  otros presupuestos) de un producto, con el almacén exacto de cada uno.
  Úsala siempre que el usuario pregunte qué números de serie o qué
  almacenes hay disponibles, y también antes de proponer una línea en
  estado "second_hand"/"ex_demo" si el usuario menciona un almacén
  concreto (para comprobar que hay unidades ahí antes de proponerlo).
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
2. Busca el cliente y cada artículo en los listados de más abajo, usando
   coincidencia semántica (no solo textual) como se explica arriba. Si hay
   varias interpretaciones razonables (p. ej. una referencia con y sin
   opción "doble pantalla"), elige la más directa pero dilo explícitamente
   en tu respuesta y ofrece la alternativa, por si el usuario prefiere
   corregirte antes de confirmar.
3. Si de verdad no hay ningún candidato razonable, o hay ambigüedad real
   entre opciones igual de plausibles, NO asumas: responde con texto
   normal preguntando al usuario que aclare, y espera su respuesta.
4. Nunca inventes un id, default_code, nombre o email que no aparezca
   literalmente en los listados de más abajo.
5. Cuando cliente y TODAS las líneas estén resueltos, llama a
   propose_quote con partner_id y las líneas (product_id + quantity).
6. Si el usuario pide cambiar la tarifa/lista de precios, indica que no se
   puede desde el chat: se aplica automáticamente la tarifa del cliente.
7. Responde siempre en español, breve y claro.

Estado de las unidades (2ª Mano / Ex-Demo):
Cada producto del listado incluye "second_hand_available" y "ex_demo_available"
(número de unidades físicas concretas disponibles en cada estado, ya
descontando lo reservado en otros presupuestos). Por defecto toda línea es
de producto Nuevo (no hace falta indicar nada). Usa "state": "second_hand" o
"state": "ex_demo" en una línea SOLO si el usuario lo pide explícitamente
("de segunda mano", "2ª mano", "ex demo", "ex-demo"), y nunca pidas más
cantidad en ese estado que el número disponible indicado para ese producto.
Si el usuario pide más unidades de las disponibles en ese estado, dile
cuántas hay realmente y pregúntale si quiere completar el resto como
producto Nuevo (en ese caso, propón dos líneas separadas para el mismo
producto: una con "state" del estado pedido y la cantidad disponible, y otra
con "state": "new" y el resto). Si no hay ninguna unidad disponible en el
estado pedido, dilo claramente y no propongas esa línea.

Almacén: si el usuario pide las unidades de 2ª mano/ex-demo de un almacén
concreto (p. ej. "que sean del almacén de Sevilla"), usa primero
list_available_serials para comprobar en qué almacenes hay unidades libres
de ese producto, y pasa ese almacén en el campo "location" de la línea al
llamar a propose_quote (tal cual aparece en el resultado de
list_available_serials). Si no hay ninguna unidad de ese estado en el
almacén pedido, dilo claramente en vez de proponer una de otro almacén sin
avisar."""

LIST_AVAILABLE_SERIALS_TOOL = {
    "name": "list_available_serials",
    "description": (
        "Devuelve los números de serie disponibles (2ª Mano/Ex-Demo, no "
        "vendidos ni reservados en otro presupuesto activo) de un producto, "
        "con el almacén de cada uno. Úsala cuando el usuario pregunte qué "
        "series o almacenes hay disponibles, o antes de proponer una línea "
        "en un almacén concreto."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "product_id": {
                "type": "integer",
                "description": "id del producto, tal cual aparece en el listado de productos.",
            },
        },
        "required": ["product_id"],
    },
}

PROPOSE_QUOTE_TOOL = {
    "name": "propose_quote",
    "description": (
        "Entrega la propuesta final de presupuesto (cliente + líneas) para "
        "que el usuario la revise y confirme. NO crea ningún registro en "
        "Odoo — es la única forma que tienes de terminar tu trabajo. Llama "
        "a esta herramienta solo cuando el cliente y TODAS las líneas estén "
        "resueltos sin ambigüedad contra los listados del prompt."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "partner_id": {
                "type": "integer",
                "description": "id del cliente resuelto, tal cual aparece en el listado de clientes.",
            },
            "lines": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "product_id": {
                            "type": "integer",
                            "description": "id del producto resuelto, tal cual aparece en el listado de productos.",
                        },
                        "quantity": {
                            "type": "number",
                            "description": "cantidad solicitada.",
                        },
                        "state": {
                            "type": "string",
                            "enum": ["new", "second_hand", "ex_demo"],
                            "description": (
                                "Estado de las unidades de esta línea. Omite este campo "
                                "(o usa 'new') salvo que el usuario pida explícitamente "
                                "'de segunda mano'/'2ª mano' o 'ex demo'/'ex-demo', y solo "
                                "hasta el límite de 'second_hand_available'/'ex_demo_available' "
                                "del producto."
                            ),
                        },
                        "location": {
                            "type": "string",
                            "description": (
                                "Almacén concreto para las unidades de 2ª mano/ex-demo de "
                                "esta línea, SOLO si el usuario lo ha pedido explícitamente "
                                "(tal cual aparece en el resultado de list_available_serials). "
                                "Omite este campo si no lo ha pedido."
                            ),
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
    def send_message(self, messages, pinned_opportunity_id=None):
        """messages: [{'role': 'user'|'assistant', 'text': str}, ...] — the
        full visible chat transcript so far, ending with the latest user
        message. Stateless: the caller resends the whole transcript every
        time. Runs the LLM tool-use loop entirely server-side, under the
        calling user's own permissions (no sudo on any business model) —
        the partner/product catalog embedded in the prompt is therefore
        already scoped by whatever record rules apply to the calling user
        (e.g. a comercial only sees their own assigned contacts).

        pinned_opportunity_id: set when the chat was opened from within a
        crm.lead record (see the "Presupuesto con IA" button added to the
        opportunity form) — the resulting quote is always linked to that
        opportunity, and the model is told to default to its customer.

        Dispatches to the configured provider (rms_ai_quote_assistant.
        llm_provider, default "anthropic"; "gemini" is a temporary
        alternative for testing while an Anthropic key is obtained — see
        _run_gemini_loop). Both branches return the same contract:
          {'type': 'message', 'text': ...}
          {'type': 'proposal', 'text': ..., 'partner_id': int, 'lines': [...],
           'opportunities': [...] or None if pinned}
          {'type': 'error', 'text': ...}
        """
        static_prompt, dynamic_hint = self._build_system_prompt(pinned_opportunity_id)

        if self._get_provider() == "gemini":
            api_key = self._get_gemini_api_key()
            if not api_key:
                return {
                    "type": "error",
                    "text": (
                        "Falta configurar la clave de la API de Gemini. "
                        "Ajustes > Técnico > Parámetros del sistema > "
                        "rms_ai_quote_assistant.gemini_api_key"
                    ),
                }
            return self._run_gemini_loop(
                api_key, self._get_gemini_model(), static_prompt + dynamic_hint,
                messages, pinned_opportunity_id,
            )

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
        return self._run_anthropic_loop(
            api_key, self._get_model(), static_prompt, dynamic_hint, messages,
            pinned_opportunity_id,
        )

    def _run_anthropic_loop(self, api_key, model, static_prompt, dynamic_hint, messages, pinned_opportunity_id):
        # The large, stable catalog dump (static_prompt) is sent as its own
        # system content block with a prompt-caching breakpoint, so it's
        # billed at full price only on the first turn/message of each
        # ~5-minute window — every following turn reads it from cache at
        # ~10% of the input price. The per-conversation, per-opportunity
        # dynamic_hint is a separate, uncached block placed AFTER the
        # breakpoint: any byte before a cache_control breakpoint invalidates
        # it, so the hint must never be concatenated in front of the catalog.
        system = [
            {
                "type": "text",
                "text": static_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ]
        if dynamic_hint:
            system.append({"type": "text", "text": dynamic_hint})

        anthropic_messages = [
            {"role": m["role"], "content": m["text"]} for m in messages
        ]
        tools = [PROPOSE_QUOTE_TOOL, LIST_AVAILABLE_SERIALS_TOOL]

        for _round in range(MAX_TOOL_ROUNDS):
            try:
                response = self._call_anthropic(
                    api_key, model, system, anthropic_messages, tools
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
                    "opportunities": (
                        None if pinned_opportunity_id
                        else self._get_partner_opportunities(preview["partner_id"])
                    ),
                }

            serial_blocks = [b for b in tool_use_blocks if b["name"] == "list_available_serials"]
            if serial_blocks:
                anthropic_messages.append({"role": "assistant", "content": content_blocks})
                tool_results = []
                for block in serial_blocks:
                    try:
                        serials = self._list_available_serials(block["input"]["product_id"])
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block["id"],
                            "content": json.dumps(serials, ensure_ascii=False),
                        })
                    except Exception as exc:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block["id"],
                            "content": str(exc),
                            "is_error": True,
                        })
                anthropic_messages.append({"role": "user", "content": tool_results})
                continue

            if not tool_use_blocks:
                if text_blocks:
                    return {"type": "message", "text": " ".join(text_blocks)}
                # No text and no tool call at all — seen in practice on
                # complex first turns (likely a truncated/paused
                # generation). Log full diagnostics and retry within the
                # existing round budget instead of dead-ending the chat;
                # resending the identical request has been observed to
                # succeed on the next attempt.
                _logger.warning(
                    "Respuesta de Anthropic sin texto ni tool_use (stop_reason=%s): %s",
                    response.get("stop_reason"), content_blocks,
                )
                continue

            # Unknown tool call (propose_quote is the only declared tool) —
            # report it back so the model can self-correct.
            anthropic_messages.append({"role": "assistant", "content": content_blocks})
            anthropic_messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": block["id"],
                            "content": "Herramienta desconocida: %s" % block["name"],
                            "is_error": True,
                        }
                        for block in tool_use_blocks
                    ],
                }
            )

        return {
            "type": "message",
            "text": (
                "No he podido resolver la petición. ¿Puedes darme más "
                "detalles sobre el cliente o los productos exactos?"
            ),
        }

    def _run_gemini_loop(self, api_key, model, system_prompt, messages, pinned_opportunity_id):
        """Gemini (function calling) counterpart of _run_anthropic_loop.

        Kept as an independent, self-contained loop rather than sharing a
        normalized format with the Anthropic branch: Gemini's message shape
        (roles "user"/"model", functionCall/functionResponse parts, no
        tool-call id to correlate on) is different enough from Anthropic's
        (roles "user"/"assistant", tool_use/tool_result blocks keyed by id)
        that forcing a common internal representation would add conversion
        bugs for little benefit — two straightforward loops are easier to
        verify independently. Only the external return contract (and the
        pure-Python helpers _build_quote_preview/_format_preview_text) are
        shared.
        """
        contents = [
            {
                "role": "user" if m["role"] == "user" else "model",
                "parts": [{"text": m["text"]}],
            }
            for m in messages
        ]
        tools = [{"functionDeclarations": [
            self._to_gemini_declaration(PROPOSE_QUOTE_TOOL),
            self._to_gemini_declaration(LIST_AVAILABLE_SERIALS_TOOL),
        ]}]

        for _round in range(MAX_TOOL_ROUNDS):
            try:
                response = self._call_gemini(api_key, model, system_prompt, contents, tools)
            except Exception:
                _logger.exception("Error llamando a la API de Gemini")
                return {
                    "type": "error",
                    "text": "No se pudo contactar con el servicio de IA. Inténtalo de nuevo.",
                }

            candidates = response.get("candidates") or []
            parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
            function_calls = [p["functionCall"] for p in parts if "functionCall" in p]
            text_parts = [p["text"] for p in parts if "text" in p]

            propose_call = next(
                (fc for fc in function_calls if fc["name"] == "propose_quote"), None
            )
            if propose_call:
                args = propose_call.get("args") or {}
                try:
                    preview = self._build_quote_preview(
                        args.get("partner_id"), args.get("lines") or []
                    )
                except ValueError as exc:
                    contents.append({"role": "model", "parts": parts})
                    contents.append(
                        {
                            "role": "user",
                            "parts": [
                                {
                                    "functionResponse": {
                                        "name": "propose_quote",
                                        "response": {"error": str(exc)},
                                    }
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
                    "opportunities": (
                        None if pinned_opportunity_id
                        else self._get_partner_opportunities(preview["partner_id"])
                    ),
                }

            serial_calls = [fc for fc in function_calls if fc["name"] == "list_available_serials"]
            if serial_calls:
                contents.append({"role": "model", "parts": parts})
                response_parts = []
                for fc in serial_calls:
                    args = fc.get("args") or {}
                    try:
                        serials = self._list_available_serials(args.get("product_id"))
                        response_parts.append({
                            "functionResponse": {
                                "name": "list_available_serials",
                                "response": {"serials": serials},
                            }
                        })
                    except Exception as exc:
                        response_parts.append({
                            "functionResponse": {
                                "name": "list_available_serials",
                                "response": {"error": str(exc)},
                            }
                        })
                contents.append({"role": "user", "parts": response_parts})
                continue

            if not function_calls:
                if text_parts:
                    return {"type": "message", "text": " ".join(text_parts)}
                _logger.warning(
                    "Respuesta de Gemini sin texto ni functionCall (finishReason=%s): %s",
                    candidates[0].get("finishReason") if candidates else None, parts,
                )
                continue

            # Unknown function call (propose_quote is the only declared tool).
            contents.append({"role": "model", "parts": parts})
            contents.append(
                {
                    "role": "user",
                    "parts": [
                        {
                            "functionResponse": {
                                "name": fc["name"],
                                "response": {"error": "Herramienta desconocida: %s" % fc["name"]},
                            }
                        }
                        for fc in function_calls
                    ],
                }
            )

        return {
            "type": "message",
            "text": (
                "No he podido resolver la petición. ¿Puedes darme más "
                "detalles sobre el cliente o los productos exactos?"
            ),
        }

    @api.model
    def confirm_quote(self, partner_id, lines, opportunity_id=None, new_opportunity_name=None):
        """Deterministic, non-LLM creation of exactly one sale.order, called
        only when the user clicks "Confirmar" on a previously shown
        proposal. lines: [{'product_id': int, 'quantity': float}, ...]

        opportunity_id: link the quote to this existing crm.lead (either the
        pinned opportunity when opened from its form, or one the user chose
        from the selector shown after the proposal).
        new_opportunity_name: instead create a new crm.lead with this name
        for the resolved partner, then link the quote to it. At most one of
        opportunity_id/new_opportunity_name is expected to be set.
        """
        try:
            preview = self._build_quote_preview(partner_id, lines)
        except ValueError as exc:
            return {"type": "error", "text": str(exc)}

        partner = self.env["res.partner"].browse(partner_id)

        if new_opportunity_name:
            opportunity = self.env["crm.lead"].create({
                "name": new_opportunity_name,
                "partner_id": partner.id,
                "type": "opportunity",
            })
            opportunity_id = opportunity.id
        elif opportunity_id:
            opportunity = self.env["crm.lead"].browse(opportunity_id).exists()
            if not opportunity:
                return {"type": "error", "text": "No existe ninguna oportunidad con id %s." % opportunity_id}

        order_vals = {
            "partner_id": partner.id,
            "order_line": [
                (0, 0, {
                    "product_id": l["product_id"],
                    "product_uom_qty": l["quantity"],
                    "sequence": (idx + 1) * 10,
                })
                for idx, l in enumerate(lines)
            ],
        }
        if opportunity_id:
            order_vals["opportunity_id"] = opportunity_id
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
            created_lines = order.order_line.sorted("sequence")
            for order_line, line in zip(created_lines, lines):
                lot_ids = line.get("lot_ids") or []
                state = line.get("state") or "new"
                if state != "new" and lot_ids:
                    self.env["sale.order.line.serial"].create([
                        {"sale_order_line_id": order_line.id, "lot_id": lot_id}
                        for lot_id in lot_ids
                    ])
        except Exception as exc:
            self.env.cr.rollback()
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
    # Catalog prompt + quote preview — run under self.env, i.e. the calling
    # user's own permissions and record rules (never sudo).
    # ---------------------------------------------------------------------

    def _build_system_prompt(self, pinned_opportunity_id=None):
        """Returns (static_prompt, dynamic_hint), split so callers can put a
        prompt-caching breakpoint after static_prompt: it's identical across
        every conversation and every user (the intro + the full partner/
        product catalog), while dynamic_hint (the pinned-opportunity note)
        varies per conversation and must stay out of the cached prefix.
        """
        partners = self.env["res.partner"].search_read(
            [], ["id", "name", "email", "phone"], order="name"
        )
        products = self.env["product.product"].search_read(
            [], ["id", "default_code", "name", "list_price", "qty_available"], order="name"
        )
        availability = self._get_special_state_availability()
        for product in products:
            entry = availability.get(product["id"], {})
            product["second_hand_available"] = entry.get("second_hand", 0)
            product["ex_demo_available"] = entry.get("ex_demo", 0)
        static_prompt = (
            SYSTEM_PROMPT_INTRO
            + "\n\nCLIENTES (JSON — usa exclusivamente estos ids, no inventes ninguno):\n"
            + json.dumps(partners, ensure_ascii=False)
            + "\n\nPRODUCTOS (JSON — usa exclusivamente estos ids, no inventes ninguno):\n"
            + json.dumps(products, ensure_ascii=False)
        )

        dynamic_hint = ""
        if pinned_opportunity_id:
            opportunity = self.env["crm.lead"].browse(pinned_opportunity_id).exists()
            if opportunity and opportunity.partner_id:
                dynamic_hint = (
                    '\n\nEsta conversación se ha abierto desde la oportunidad '
                    '"%s", cuyo cliente es "%s" (id=%s). Si el usuario no '
                    "menciona explícitamente un cliente distinto, usa ese "
                    "cliente sin preguntar." % (
                        opportunity.name, opportunity.partner_id.name, opportunity.partner_id.id,
                    )
                )
        return static_prompt, dynamic_hint

    def _get_special_state_availability(self):
        """{product_id: {'second_hand': n, 'ex_demo': n}} counting distinct
        stock.lot units in each state that are physically in an internal
        location and not already committed to another active order line
        (sale.order.line.serial), i.e. genuinely offerable right now.
        """
        Lot = self.env["stock.lot"]
        lots = Lot.search([("product_state_id.code", "in", ("second_hand", "ex_demo"))])
        if not lots:
            return {}
        sold_lot_ids = set(
            self.env["sale.order.line.serial"].search([
                ("lot_id", "in", lots.ids),
                ("sale_order_line_id.order_id.state", "!=", "cancel"),
            ]).lot_id.ids
        )
        quants = self.env["stock.quant"].search([
            ("lot_id", "in", lots.ids), ("location_id.usage", "=", "internal"),
        ])
        in_stock_lot_ids = set(quants.filtered(lambda q: q.quantity > 0).lot_id.ids)
        availability = {}
        for lot in lots:
            if lot.id in sold_lot_ids or lot.id not in in_stock_lot_ids:
                continue
            entry = availability.setdefault(lot.product_id.id, {"second_hand": 0, "ex_demo": 0})
            entry[lot.product_state_id.code] += 1
        return availability

    def _get_free_lots(self, product_id, state):
        """stock.lot recordset of `product_id` in `state` that are
        physically in stock and not committed to another active order
        line. Shared by _pick_available_lots and _list_available_serials
        so both use exactly the same availability rules.
        """
        Lot = self.env["stock.lot"]
        candidates = Lot.search([
            ("product_id", "=", product_id),
            ("product_state_id.code", "=", state),
        ])
        if not candidates:
            return candidates
        sold_ids = set(
            self.env["sale.order.line.serial"].search([
                ("lot_id", "in", candidates.ids),
                ("sale_order_line_id.order_id.state", "!=", "cancel"),
            ]).lot_id.ids
        )
        quants = self.env["stock.quant"].search([
            ("lot_id", "in", candidates.ids), ("location_id.usage", "=", "internal"),
        ])
        in_stock_ids = set(quants.filtered(lambda q: q.quantity > 0).lot_id.ids)
        return candidates.filtered(lambda l: l.id in in_stock_ids and l.id not in sold_ids)

    def _list_available_serials(self, product_id):
        """[{'lot_id', 'name', 'state', 'location'}, ...] for every free
        serial of `product_id` in 2ª Mano or Ex-Demo. Backs the
        list_available_serials tool the LLM can call on demand.
        """
        result = []
        for state, label in (("second_hand", "second_hand"), ("ex_demo", "ex_demo")):
            for lot in self._get_free_lots(product_id, state):
                result.append({
                    "lot_id": lot.id,
                    "name": lot.name,
                    "state": label,
                    "location": lot.location_id.display_name or "",
                })
        return result

    def _pick_available_lots(self, product_id, state, quantity, location=None):
        """Returns up to `quantity` free stock.lot ids of `product_id` in
        `state` ('second_hand'/'ex_demo'), raising ValueError (surfaced to
        the LLM as a tool error, or to the user on confirm) if there aren't
        enough. Mirrors the manual wizard's own availability filter.

        location: optional substring (case-insensitive) to match against
        each candidate lot's warehouse/location display name — set only
        when the user explicitly asked for units from a specific
        warehouse; narrows the pool instead of picking from anywhere.
        """
        available = self._get_free_lots(product_id, state)
        if location:
            in_location = available.filtered(
                lambda l: location.lower() in (l.location_id.display_name or "").lower()
            )
            if not in_location:
                raise ValueError(
                    "No hay ninguna unidad disponible en estado '%s' en el almacén "
                    "'%s' para este producto." % (state, location)
                )
            available = in_location
        needed = int(quantity)
        if len(available) < needed:
            raise ValueError(
                "Solo hay %s unidad(es) disponible(s) en estado '%s'%s para este "
                "producto (se pidieron %s)." % (
                    len(available), state,
                    " en el almacén '%s'" % location if location else "",
                    needed,
                )
            )
        return available[:needed].ids

    def _get_partner_opportunities(self, partner_id):
        return self.env["crm.lead"].search_read(
            [("partner_id", "=", partner_id), ("type", "=", "opportunity"), ("active", "=", True)],
            ["id", "name"],
            order="create_date desc",
        )

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
            state = line.get("state") or "new"
            if state not in ("new", "second_hand", "ex_demo"):
                raise ValueError("Estado de línea no válido: %s." % state)
            quantity = line["quantity"]
            lot_ids = []
            if state != "new":
                lot_ids = self._pick_available_lots(
                    product.id, state, quantity, location=line.get("location")
                )
                quantity = len(lot_ids)
            line_previews.append(
                {
                    "product_id": product.id,
                    "name": product.display_name,
                    "default_code": product.default_code or "",
                    "quantity": quantity,
                    "state": state,
                    "lot_ids": lot_ids,
                }
            )
        return {
            "partner_id": partner.id,
            "partner_name": partner.name,
            "partner_email": partner.email or "",
            "lines": line_previews,
        }

    def _format_preview_text(self, preview):
        state_labels = {"second_hand": " [2ª Mano]", "ex_demo": " [Ex-Demo]"}
        lines_txt = "\n".join(
            "- %s x %s (%s)%s"
            % (l["quantity"], l["name"], l["default_code"], state_labels.get(l.get("state"), ""))
            for l in preview["lines"]
        )
        return (
            "Cliente: %s (%s)\n%s\n\n¿Confirmas la creación de este presupuesto?"
            % (preview["partner_name"], preview["partner_email"], lines_txt)
        )

    # ---------------------------------------------------------------------
    # Config + HTTP
    # ---------------------------------------------------------------------

    def _get_provider(self):
        return self.env["ir.config_parameter"].sudo().get_param(
            "rms_ai_quote_assistant.llm_provider", "anthropic"
        )

    def _get_api_key(self):
        return self.env["ir.config_parameter"].sudo().get_param(
            "rms_ai_quote_assistant.anthropic_api_key"
        )

    def _get_model(self):
        return self.env["ir.config_parameter"].sudo().get_param(
            "rms_ai_quote_assistant.anthropic_model", "claude-sonnet-5"
        )

    def _get_anthropic_workspace_id(self):
        # Only required for "identity-linked" API keys (created under an
        # Anthropic Console organization/workspace) — the Messages API
        # rejects those without an explicit anthropic-workspace-id header
        # naming which workspace the request acts in. Plain personal keys
        # don't need this, so it stays optional.
        return self.env["ir.config_parameter"].sudo().get_param(
            "rms_ai_quote_assistant.anthropic_workspace_id"
        )

    def _get_gemini_api_key(self):
        return self.env["ir.config_parameter"].sudo().get_param(
            "rms_ai_quote_assistant.gemini_api_key"
        )

    def _get_gemini_model(self):
        return self.env["ir.config_parameter"].sudo().get_param(
            "rms_ai_quote_assistant.gemini_model", "gemini-2.5-flash"
        )

    def _to_gemini_declaration(self, tool):
        return {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["input_schema"],
        }

    def _call_gemini(self, api_key, model, system, contents, tools):
        payload = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": contents,
            "tools": tools,
        }
        response = requests.post(
            "%s/%s:generateContent" % (GEMINI_API_BASE_URL, model),
            params={"key": api_key},
            headers={"content-type": "application/json"},
            json=payload,
            timeout=LLM_TIMEOUT,
        )
        if not response.ok:
            _logger.error("Gemini API error %s: %s", response.status_code, response.text[:2000])
        response.raise_for_status()
        return response.json()

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
