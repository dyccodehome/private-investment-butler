from __future__ import annotations

import unittest

from src.communication_gate import _build_interactive_card


class CommunicationGateTest(unittest.TestCase):
    def test_interactive_card_button_uses_callback_behavior(self) -> None:
        card = _build_interactive_card(
            "chat-1",
            "测试卡片",
            "正文",
            [{"label": "同意", "action": "accept_constitution_patch", "type": "primary", "state_id": "state-1"}],
        )

        button = card["elements"][1]["actions"][0]
        expected_value = {
            "chat_id": "chat-1",
            "action": "accept_constitution_patch",
            "state_id": "state-1",
        }

        self.assertEqual(button["value"], expected_value)
        self.assertEqual(button["behaviors"], [{"type": "callback", "value": expected_value}])


if __name__ == "__main__":
    unittest.main()
