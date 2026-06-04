from __future__ import annotations

import unittest

from src.communication_gate import _build_interactive_card, _build_post_content


class CommunicationGateTest(unittest.TestCase):
    def test_interactive_card_button_uses_callback_behavior(self) -> None:
        card = _build_interactive_card(
            "chat-1",
            "测试卡片",
            "正文",
            [
                {
                    "label": "同意",
                    "action": "accept_constitution_patch",
                    "type": "primary",
                    "state_id": "state-1",
                    "framework_id": "Cash_Anchor",
                    "patch_id": "CASH-1",
                    "reason": "smoke reason",
                }
            ],
        )

        button = card["elements"][1]["actions"][0]
        expected_value = {
            "chat_id": "chat-1",
            "action": "accept_constitution_patch",
            "state_id": "state-1",
            "framework_id": "Cash_Anchor",
            "patch_id": "CASH-1",
            "reason": "smoke reason",
        }

        self.assertEqual(button["value"], expected_value)
        self.assertEqual(button["behaviors"], [{"type": "callback", "value": expected_value}])

    def test_post_content_uses_markdown_block(self) -> None:
        content = _build_post_content("**结论**\n- 先看到账流水")

        block = content["zh_cn"]["content"][0][0]
        self.assertEqual(block["tag"], "md")
        self.assertIn("先看到账流水", block["text"])


if __name__ == "__main__":
    unittest.main()
