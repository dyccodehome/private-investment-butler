from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from src import longbridge_quote_provider as quote_provider


class LongbridgeQuoteProviderTest(unittest.TestCase):
    def test_fetch_kline_uses_fixed_readonly_command(self) -> None:
        completed = type(
            "Completed",
            (),
            {
                "returncode": 0,
                "stdout": json.dumps(
                    [
                        {"time": "2026-06-01", "open": "10", "high": "12", "low": "9", "close": "11"},
                        {"time": "2026-06-02", "open": "11", "high": "13", "low": "10", "close": "12"},
                    ]
                ),
                "stderr": "",
            },
        )()
        with patch("src.longbridge_quote_provider.subprocess.run", return_value=completed) as run:
            payload = quote_provider.fetch_kline("NVDA.US", period="day", count=2, timeout_seconds=3)

        self.assertEqual(
            run.call_args.args[0],
            ["longbridge", "kline", "NVDA.US", "--period", "day", "--count", "2", "--format", "json"],
        )
        self.assertFalse(run.call_args.kwargs.get("shell", False))
        self.assertEqual(run.call_args.kwargs["timeout"], 3)
        self.assertEqual(payload["summary"]["kline_count"], 2)
        self.assertEqual(payload["data"]["technical"]["latest_close"], 12)

    def test_fetch_market_status_uses_fixed_readonly_command(self) -> None:
        completed = type(
            "Completed",
            (),
            {
                "returncode": 0,
                "stdout": json.dumps([{"market": "US", "status": "Pre-Market"}]),
                "stderr": "",
            },
        )()
        with patch("src.longbridge_quote_provider.subprocess.run", return_value=completed) as run:
            payload = quote_provider.fetch_market_status(timeout_seconds=3)

        self.assertEqual(run.call_args.args[0], ["longbridge", "market-status", "--format", "json"])
        self.assertEqual(payload["summary"]["market_count"], 1)

    def test_build_market_context_snapshot_is_partial_tolerant(self) -> None:
        with patch("src.longbridge_quote_provider.fetch_market_status") as market_status, patch(
            "src.longbridge_quote_provider.fetch_trading_days"
        ) as trading_days, patch("src.longbridge_quote_provider.fetch_trading_sessions") as sessions, patch(
            "src.longbridge_quote_provider.fetch_market_temperature"
        ) as temperature, patch("src.longbridge_quote_provider.fetch_realtime_quotes") as quotes, patch(
            "src.longbridge_quote_provider.fetch_kline"
        ) as kline:
            market_status.return_value = {"summary": {"market_count": 1}, "data": [{"market": "US"}]}
            trading_days.return_value = {"summary": {"trading_day_count": 5}, "data": {"trading_days": []}}
            sessions.return_value = {"summary": {"market_count": 1}, "data": []}
            temperature.return_value = {"summary": {"temperature": 55}, "data": {}}
            quotes.return_value = {
                "summary": {"quote_count": 1},
                "data": {
                    "NVDA.US": {
                        "symbol": "NVDA.US",
                        "current_price": 120,
                        "quote_source": "last",
                        "timestamp": "",
                    }
                },
            }
            kline.side_effect = RuntimeError("quota exceeded")

            snapshot = quote_provider.build_market_context_snapshot(symbols=["NVDA.US"], market="US")

        self.assertEqual(snapshot["data_quality"]["status"], "partial")
        self.assertEqual(snapshot["summary"]["quote_count"], 1)
        self.assertIn("NVDA.US", snapshot["symbol_data"])
        self.assertTrue(any("quota exceeded" in item for item in snapshot["data_quality"]["limitations"]))


if __name__ == "__main__":
    unittest.main()
