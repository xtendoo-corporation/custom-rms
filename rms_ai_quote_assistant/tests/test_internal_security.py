from unittest.mock import patch

from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged("post_install", "-at_install")
class TestInternalSecurity(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.portal = new_test_user(cls.env, login="s1_portal", groups="base.group_portal")
        cls.internal = new_test_user(cls.env, login="s1_internal", groups="base.group_user,sales_team.group_sale_salesman,stock.group_stock_user")

    def test_send_access(self):
        model = self.env["rms.ai.quote.assistant"]
        with patch.object(type(model), "_build_system_prompt") as prompt, patch.object(type(model), "_get_provider") as provider:
            with self.assertRaises(AccessError):
                model.with_user(self.portal).send_message([])
            prompt.assert_not_called()
            provider.assert_not_called()
        self.env["ir.config_parameter"].sudo().set_param("rms_ai_quote_assistant.anthropic_api_key", "test-key")
        self.env["ir.config_parameter"].sudo().set_param("rms_ai_quote_assistant.llm_provider", "anthropic")
        response = {"stop_reason": "end_turn", "content": [{"type": "text", "text": "Respuesta de prueba"}]}
        with patch.object(type(model), "_call_anthropic", return_value=response) as provider:
            result = model.with_user(self.internal).send_message([{"role": "user", "text": "Hola"}])
            self.assertEqual(result["type"], "message")
            provider.assert_called_once()
        with patch.object(type(model), "_call_anthropic", return_value=response):
            self.assertEqual(model.with_user(self.portal).sudo().send_message([])["type"], "message")

    def test_confirm_access(self):
        model = self.env["rms.ai.quote.assistant"]
        with patch.object(type(model), "_build_quote_preview") as preview:
            with self.assertRaises(AccessError):
                model.with_user(self.portal).confirm_quote(0, [])
            preview.assert_not_called()
        salesperson = new_test_user(self.env, login="s1_sales", groups="base.group_user,sales_team.group_sale_salesman")
        partner = self.env["res.partner"].create({"name": "S1 cliente", "user_id": salesperson.id})
        product = self.env["product.product"].create({"name": "S1 servicio", "type": "service", "list_price": 10})
        result = model.with_user(salesperson).confirm_quote(partner.id, [{"product_id": product.id, "quantity": 1}])
        self.assertEqual(result["type"], "result")
        self.assertEqual(self.env["sale.order"].browse(result["order_id"]).partner_id, partner)

    def test_gemini_provider_access(self):
        model = self.env["rms.ai.quote.assistant"]
        config = self.env["ir.config_parameter"].sudo()
        config.set_param("rms_ai_quote_assistant.llm_provider", "gemini")
        config.set_param("rms_ai_quote_assistant.gemini_api_key", "test-key")
        response = {"candidates": [{"content": {"parts": [{"text": "Respuesta de prueba"}]}}]}
        with patch.object(type(model), "_call_gemini", return_value=response) as provider:
            with self.assertRaises(AccessError):
                model.with_user(self.portal).send_message([])
            provider.assert_not_called()
            self.assertEqual(model.with_user(self.internal).send_message([])["type"], "message")
            provider.assert_called_once()
