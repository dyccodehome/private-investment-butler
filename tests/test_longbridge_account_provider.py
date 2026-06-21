from __future__ import annotations

import json
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from src import longbridge_account_provider as account_provider


class LongbridgeAccountProviderTest(unittest.TestCase):
    def test_fetch_account_assets_uses_fixed_readonly_command(self) -> None:
        completed = SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"cash_infos": [{"currency": "USD"}]}),
            stderr="",
        )
        with patch("src.longbridge_account_provider.subprocess.run", return_value=completed) as run:
            payload = account_provider.fetch_account_assets(currency="usd", timeout_seconds=3)

        self.assertEqual(run.call_args.args[0], ["longbridge", "assets", "--currency", "USD", "--format", "json"])
        self.assertFalse(run.call_args.kwargs.get("shell", False))
        self.assertEqual(run.call_args.kwargs["timeout"], 3)
        self.assertEqual(payload["scope"], "account_assets")
        self.assertEqual(payload["summary"]["cash_info_count"], 1)
        self.assertIn("no order placement", payload["write_policy"])

    def test_fetch_order_and_execution_history_use_query_commands(self) -> None:
        completed = SimpleNamespace(returncode=0, stdout=json.dumps([{"order_id": "o1"}]), stderr="")
        with patch("src.longbridge_account_provider.subprocess.run", return_value=completed) as run:
            orders = account_provider.fetch_order_history(
                start=date(2026, 6, 1),
                end=date(2026, 6, 21),
                symbol="nvda.us",
                timeout_seconds=3,
            )
            executions = account_provider.fetch_execution_history(
                start="2026-06-01",
                end="2026-06-21",
                symbol="nvda.us",
                timeout_seconds=3,
            )

        self.assertEqual(
            run.call_args_list[0].args[0],
            [
                "longbridge",
                "order",
                "--history",
                "--start",
                "2026-06-01",
                "--end",
                "2026-06-21",
                "--symbol",
                "NVDA.US",
                "--format",
                "json",
            ],
        )
        self.assertEqual(
            run.call_args_list[1].args[0],
            [
                "longbridge",
                "order",
                "executions",
                "--history",
                "--start",
                "2026-06-01",
                "--end",
                "2026-06-21",
                "--symbol",
                "NVDA.US",
                "--format",
                "json",
            ],
        )
        self.assertEqual(orders["summary"]["order_count"], 1)
        self.assertEqual(executions["summary"]["execution_count"], 1)

    def test_snapshot_is_partial_tolerant(self) -> None:
        with patch("src.longbridge_account_provider.fetch_account_assets") as assets, patch(
            "src.longbridge_account_provider.fetch_portfolio_overview"
        ) as portfolio, patch("src.longbridge_account_provider.fetch_order_history") as orders, patch(
            "src.longbridge_account_provider.fetch_execution_history"
        ) as executions:
            assets.return_value = {"summary": {"cash_info_count": 2}}
            portfolio.return_value = {"summary": {"holding_count": 3}}
            orders.side_effect = RuntimeError("order query failed")
            executions.return_value = {"summary": {"execution_count": 4}}

            snapshot = account_provider.build_account_activity_snapshot(
                days=7,
                end=date(2026, 6, 21),
                currency="USD",
                timeout_seconds=3,
            )

        self.assertEqual(snapshot["status"], "partial")
        self.assertEqual(snapshot["period"], {"start": "2026-06-14", "end": "2026-06-21", "days": 7})
        self.assertEqual(snapshot["summary"]["cash_info_count"], 2)
        self.assertEqual(snapshot["summary"]["holding_count"], 3)
        self.assertEqual(snapshot["summary"]["order_count"], 0)
        self.assertEqual(snapshot["summary"]["execution_count"], 4)
        self.assertIn("order query failed", snapshot["data_quality"]["limitations"][0])

    def test_format_account_activity_snapshot(self) -> None:
        text = account_provider.format_account_activity_snapshot(
            {
                "status": "ok",
                "period": {"start": "2026-06-01", "end": "2026-06-21"},
                "currency": "USD",
                "symbol": "NVDA.US",
                "summary": {
                    "holding_count": 3,
                    "order_count": 2,
                    "execution_count": 1,
                    "cash_info_count": 1,
                },
                "write_policy": account_provider.READ_ONLY_WRITE_POLICY,
                "data_quality": {"limitations": []},
            }
        )

        self.assertIn("长桥账户/成交只读快照", text)
        self.assertIn("NVDA.US", text)
        self.assertIn("历史成交：1", text)


if __name__ == "__main__":
    unittest.main()
