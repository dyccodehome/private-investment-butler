from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from src import trading_calendar


class TradingCalendarTest(unittest.TestCase):
    def test_us_calendar_observes_independence_day(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(trading_calendar, "CALENDAR_DIR", Path(tmp)):
                self.assertFalse(trading_calendar.is_trading_day("US", date(2026, 7, 3)))
                self.assertTrue(trading_calendar.is_trading_day("US", date(2026, 7, 6)))

    def test_manual_holiday_overrides_generated_calendar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(trading_calendar, "CALENDAR_DIR", Path(tmp)):
                self.assertFalse(
                    trading_calendar.is_trading_day(
                        "US",
                        date(2026, 7, 6),
                        manual_holidays={"2026-07-06"},
                    )
                )

    def test_cn_uses_cached_calendar_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(trading_calendar, "CALENDAR_DIR", Path(tmp)):
                payload = {
                    "schema_version": 1,
                    "market": "CN",
                    "year": 2026,
                    "source": "test",
                    "generated_at": "2026-01-01T00:00:00",
                    "trading_days": ["2026-10-09"],
                    "warnings": [],
                }
                trading_calendar.save_trading_calendar(payload)

                self.assertTrue(trading_calendar.is_trading_day("CN", date(2026, 10, 9)))
                self.assertFalse(trading_calendar.is_trading_day("CN", date(2026, 10, 8)))

    def test_cn_falls_back_to_weekday_without_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(trading_calendar, "CALENDAR_DIR", Path(tmp)):
                self.assertTrue(trading_calendar.is_trading_day("CN", date(2026, 6, 3)))
                self.assertFalse(trading_calendar.is_trading_day("CN", date(2026, 6, 6)))

    def test_build_cn_calendar_can_use_fetcher(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(trading_calendar, "CALENDAR_DIR", Path(tmp)), patch(
                "src.trading_calendar._fetch_cn_trading_days_from_akshare",
                return_value=[date(2026, 1, 5), date(2026, 1, 6)],
            ):
                payload = trading_calendar.build_trading_calendar("CN", 2026, refresh=True)

        self.assertEqual(payload["source"], "akshare_tool_trade_date_hist_sina")
        self.assertEqual(payload["trading_days"], ["2026-01-05", "2026-01-06"])


if __name__ == "__main__":
    unittest.main()
