from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from src import longbridge_fundamental_provider as fundamental_provider


class LongbridgeFundamentalProviderTest(unittest.TestCase):
    def test_fetch_company_profile_uses_fixed_readonly_command(self) -> None:
        completed = type(
            "Completed",
            (),
            {
                "returncode": 0,
                "stdout": json.dumps({"name": "NVIDIA", "market": "NASDAQ"}),
                "stderr": "",
            },
        )()
        with patch("src.longbridge_fundamental_provider.subprocess.run", return_value=completed) as run:
            payload = fundamental_provider.fetch_company_profile("NVDA.US", timeout_seconds=3)

        self.assertEqual(run.call_args.args[0], ["longbridge", "company", "NVDA.US", "--format", "json"])
        self.assertFalse(run.call_args.kwargs.get("shell", False))
        self.assertEqual(run.call_args.kwargs["timeout"], 3)
        self.assertEqual(payload["summary"]["company_name"], "NVIDIA")

    def test_fetch_financial_report_snapshot_uses_fixed_readonly_command(self) -> None:
        completed = type(
            "Completed",
            (),
            {
                "returncode": 0,
                "stdout": json.dumps({"currency": "USD", "period": "Q1 FY2026", "summary": "beat"}),
                "stderr": "",
            },
        )()
        with patch("src.longbridge_fundamental_provider.subprocess.run", return_value=completed) as run:
            payload = fundamental_provider.fetch_financial_report_snapshot("NVDA.US", report="qf", year=2026, period=1)

        self.assertEqual(
            run.call_args.args[0],
            [
                "longbridge",
                "financial-report",
                "snapshot",
                "NVDA.US",
                "--report",
                "qf",
                "--year",
                "2026",
                "--period",
                "1",
                "--format",
                "json",
            ],
        )
        self.assertEqual(payload["summary"]["currency"], "USD")

    def test_build_fundamental_context_snapshot_is_partial_tolerant(self) -> None:
        with patch("src.longbridge_fundamental_provider.fetch_company_profile") as company, patch(
            "src.longbridge_fundamental_provider.fetch_valuation"
        ) as valuation, patch("src.longbridge_fundamental_provider.fetch_financial_report_snapshot") as report, patch(
            "src.longbridge_fundamental_provider.fetch_forecast_eps"
        ) as forecast, patch("src.longbridge_fundamental_provider.fetch_consensus") as consensus, patch(
            "src.longbridge_fundamental_provider.fetch_dividend_history"
        ) as dividend:
            company.return_value = {"data": {"name": "NVIDIA", "market": "NASDAQ"}, "summary": {}}
            valuation.return_value = {
                "data": {"metrics": {"pe": {"desc": "current P/E in reasonable range"}}},
                "summary": {},
            }
            report.return_value = {"data": {"summary": "beat"}, "summary": {}}
            forecast.return_value = {"data": {"items": [{"forecast_eps_mean": "3.04"}]}, "summary": {}}
            consensus.return_value = {"data": {"list": [{"details": []}]}, "summary": {}}
            dividend.side_effect = RuntimeError("dividend unavailable")

            snapshot = fundamental_provider.build_fundamental_context_snapshot(symbols=["NVDA.US"], market="US")

        self.assertEqual(snapshot["data_quality"]["status"], "partial")
        self.assertEqual(snapshot["summary"]["company_profile_count"], 1)
        self.assertEqual(snapshot["summary"]["valuation_count"], 1)
        self.assertEqual(snapshot["symbol_data"]["NVDA.US"]["company_name"], "NVIDIA")
        self.assertTrue(any("dividend unavailable" in item for item in snapshot["data_quality"]["limitations"]))


if __name__ == "__main__":
    unittest.main()
