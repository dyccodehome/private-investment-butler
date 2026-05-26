from __future__ import annotations

import unittest
from unittest.mock import patch

from src import feishu_runtime
from src.session_lock import save_pending_action


class FeishuRuntimeTest(unittest.TestCase):
    def test_text_message_handles_command(self) -> None:
        with patch("src.feishu_runtime.communication_gate.send") as send:
            result = feishu_runtime.handle_feishu_text_message("cli", "/help", async_run=False)

        self.assertEqual(result, "command handled")
        self.assertTrue(send.called)
        self.assertIn("/contribute", send.call_args.args[1])

    def test_text_message_handles_command_after_bot_mention(self) -> None:
        with patch("src.feishu_runtime.communication_gate.send") as send:
            result = feishu_runtime.handle_feishu_text_message("cli", "@_user_1 /help", async_run=False)

        self.assertEqual(result, "command handled")
        self.assertTrue(send.called)
        self.assertIn("/contribute", send.call_args.args[1])

    def test_card_callback_handles_missing_pending_action(self) -> None:
        with patch("src.feishu_runtime.communication_gate.send") as send:
            result = feishu_runtime.handle_feishu_card_callback(
                {"chat_id": "cli", "action": "reject_constitution_patch", "state_id": "missing"}
            )

        self.assertEqual(result, "no pending action")
        send.assert_called_once()

    def test_card_callback_handles_reject_patch_action(self) -> None:
        save_pending_action(
            chat_id="cli",
            action_id="action-1",
            framework_id="Cash_Anchor",
            reason="PATCH-1",
        )
        with patch("src.feishu_runtime._handle_patch_callback") as callback:
            result = feishu_runtime.handle_feishu_card_callback(
                {"chat_id": "cli", "action": "reject_constitution_patch", "state_id": "action-1"}
            )

        self.assertEqual(result, "callback handled")
        callback.assert_called_once_with("reject_constitution_patch", "cli", "Cash_Anchor", "PATCH-1")


if __name__ == "__main__":
    unittest.main()
