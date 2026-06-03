from __future__ import annotations

import unittest
from unittest.mock import patch

from scripts import run_growth_daily_review


class GrowthDailyReviewScriptTest(unittest.TestCase):
    @patch("scripts.run_growth_daily_review.communication_gate.send")
    @patch("scripts.run_growth_daily_review.review_growth_daily")
    @patch("scripts.run_growth_daily_review.get_config")
    @patch("sys.argv", ["run_growth_daily_review.py", "--market", "CN"])
    def test_uses_default_chat_id_from_env_config(self, get_config, review_daily, send) -> None:
        get_config.return_value.messaging.return_value.default_chat_id = "oc_default"
        review_daily.return_value = "复盘结果"

        run_growth_daily_review.main()

        review_daily.assert_called_once_with("CN", chat_id="oc_default")
        send.assert_called_once_with("oc_default", "复盘结果")

    @patch("scripts.run_growth_daily_review.communication_gate.send")
    @patch("scripts.run_growth_daily_review.review_growth_daily")
    @patch("scripts.run_growth_daily_review.get_config")
    @patch("sys.argv", ["run_growth_daily_review.py", "--market", "US", "--chat-id", "oc_cli"])
    def test_cli_chat_id_overrides_default_chat_id(self, get_config, review_daily, send) -> None:
        get_config.return_value.messaging.return_value.default_chat_id = "oc_default"
        review_daily.return_value = "复盘结果"

        run_growth_daily_review.main()

        review_daily.assert_called_once_with("US", chat_id="oc_cli")
        send.assert_called_once_with("oc_cli", "复盘结果")


if __name__ == "__main__":
    unittest.main()
