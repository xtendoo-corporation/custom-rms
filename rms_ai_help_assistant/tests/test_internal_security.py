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
        cls.internal = new_test_user(cls.env, login="s1_internal", groups="base.group_user")

    def test_send_access(self):
        model = self.env["rms.ai.help.assistant"]
        with patch.object(type(model), "_get_api_key", return_value="test-key") as key:
            with self.assertRaises(AccessError):
                model.with_user(self.portal).send_message([])
            key.assert_not_called()
        self.env["ir.config_parameter"].sudo().set_param("rms_ai_help_assistant.anthropic_api_key", "test-key")
        response = {"stop_reason": "end_turn", "content": [{"type": "text", "text": "Respuesta de prueba"}]}
        with patch.object(type(model), "_call_anthropic", return_value=response) as provider:
            result = model.with_user(self.internal).send_message([{"role": "user", "text": "Hola"}])
            self.assertEqual(result["type"], "message")
            provider.assert_called_once()
        with patch.object(type(model), "_call_anthropic", return_value=response):
            self.assertEqual(model.with_user(self.portal).sudo().send_message([])["type"], "message")
