from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from src.market_phase import build_market_phase_context


class MarketPhaseTest(unittest.TestCase):
    def test_cn_intraday_phase_marks_partial_bar(self) -> None:
        phase = build_market_phase_context(
            "CN",
            now=datetime(2026, 6, 4, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        )

        self.assertEqual(phase["market"], "CN")
        self.assertEqual(phase["phase"], "intraday")
        self.assertTrue(phase["is_market_open_now"])
        self.assertTrue(phase["is_partial_bar"])

    def test_us_weekend_is_non_trading(self) -> None:
        phase = build_market_phase_context(
            "US",
            now=datetime(2026, 6, 6, 10, 0, tzinfo=ZoneInfo("America/New_York")),
        )

        self.assertEqual(phase["phase"], "non_trading")
        self.assertFalse(phase["is_market_open_now"])


if __name__ == "__main__":
    unittest.main()
