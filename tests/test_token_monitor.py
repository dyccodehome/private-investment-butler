from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from src import token_monitor


class _FakeConfig:
    def token_monitor(self) -> dict[str, object]:
        return {
            "enabled": True,
            "daily_total_token_limit": 100,
            "warning_threshold": 0.8,
        }


class TokenMonitorTest(unittest.TestCase):
    def test_token_warning_is_deduped_per_chat_and_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            token_dir = Path(tmp)
            today = datetime.now().strftime("%Y-%m-%d")
            (token_dir / f"{today}.jsonl").write_text(
                json.dumps({"total_tokens": 90}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            with patch.object(token_monitor, "TOKEN_USAGE_DIR", token_dir), patch.object(
                token_monitor,
                "TOKEN_WARNING_STATE_DIR",
                token_dir / "warning_state",
            ), patch.object(token_monitor, "get_config", return_value=_FakeConfig()):
                first = token_monitor.build_token_warning("chat-1")
                second = token_monitor.build_token_warning("chat-1")
                other_chat = token_monitor.build_token_warning("chat-2")

        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertIsNotNone(other_chat)


if __name__ == "__main__":
    unittest.main()
