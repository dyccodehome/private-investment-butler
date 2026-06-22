from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from src import longbridge_event_provider as event_provider


class LongbridgeEventProviderTest(unittest.TestCase):
    def test_fetch_symbol_news_uses_fixed_readonly_command(self) -> None:
        completed = type(
            "Completed",
            (),
            {
                "returncode": 0,
                "stdout": json.dumps([{"id": "1", "title": "NVIDIA launches new AI platform"}]),
                "stderr": "",
            },
        )()
        with patch("src.longbridge_event_provider.subprocess.run", return_value=completed) as run:
            payload = event_provider.fetch_symbol_news("NVDA.US", count=3, timeout_seconds=4)

        self.assertEqual(run.call_args.args[0], ["longbridge", "news", "NVDA.US", "--count", "3", "--format", "json"])
        self.assertFalse(run.call_args.kwargs.get("shell", False))
        self.assertEqual(run.call_args.kwargs["timeout"], 4)
        self.assertEqual(payload["summary"]["news_count"], 1)

    def test_fetch_symbol_filings_uses_fixed_readonly_command(self) -> None:
        completed = type(
            "Completed",
            (),
            {
                "returncode": 0,
                "stdout": json.dumps([{"id": "10", "title": "10-K - NVIDIA"}]),
                "stderr": "",
            },
        )()
        with patch("src.longbridge_event_provider.subprocess.run", return_value=completed) as run:
            payload = event_provider.fetch_symbol_filings("NVDA.US", timeout_seconds=4)

        self.assertEqual(run.call_args.args[0], ["longbridge", "filing", "NVDA.US", "--format", "json"])
        self.assertEqual(payload["summary"]["filing_count"], 1)

    def test_build_event_context_snapshot_is_partial_tolerant(self) -> None:
        with patch("src.longbridge_event_provider.fetch_symbol_news") as news, patch(
            "src.longbridge_event_provider.fetch_symbol_filings"
        ) as filings, patch("src.longbridge_event_provider.fetch_symbol_topics") as topics, patch(
            "src.longbridge_event_provider.fetch_finance_calendar"
        ) as calendar:
            news.return_value = {"data": [{"id": "1", "title": "NVIDIA AI demand rises"}], "summary": {}}
            filings.return_value = {"data": [{"id": "2", "title": "10-Q - NVIDIA"}], "summary": {}}
            topics.side_effect = RuntimeError("topic unavailable")
            calendar.return_value = {"data": [{"title": "earnings date"}], "summary": {}}

            snapshot = event_provider.build_event_context_snapshot(symbols=["NVDA.US"], market="US")

        self.assertEqual(snapshot["data_quality"]["status"], "partial")
        self.assertEqual(snapshot["summary"]["news_count"], 1)
        self.assertEqual(snapshot["summary"]["filing_count"], 1)
        self.assertEqual(snapshot["summary"]["calendar_event_count"], 2)
        self.assertEqual(snapshot["symbol_data"]["NVDA.US"]["news"][0]["title"], "NVIDIA AI demand rises")
        self.assertTrue(any("topic unavailable" in item for item in snapshot["data_quality"]["limitations"]))


if __name__ == "__main__":
    unittest.main()
