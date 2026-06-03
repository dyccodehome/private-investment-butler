from __future__ import annotations

import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from src import longbridge_provider
from src import portfolio_ledger


class LongbridgeProviderTest(unittest.TestCase):
    def test_parse_and_filter_cash_anchor_positions(self) -> None:
        payload = {
            "code": 0,
            "data": {
                "list": [
                    {
                        "account_channel": "lb",
                        "stock_info": [
                            {
                                "symbol": "QQQI.US",
                                "symbol_name": "NEOS Nasdaq-100 High Income ETF",
                                "currency": "USD",
                                "quantity": "100",
                                "market": "US",
                                "available": "100",
                                "cost_price": "50.25",
                            },
                            {
                                "symbol": "NVDA.US",
                                "symbol_name": "NVIDIA",
                                "currency": "USD",
                                "quantity": "10",
                                "market": "US",
                                "available_quantity": "10",
                                "cost_price": "900",
                            },
                        ],
                    }
                ]
            },
        }

        positions = longbridge_provider.parse_longbridge_positions(json.dumps(payload))
        proposal = longbridge_provider.build_cash_anchor_sync_proposal(positions)

        self.assertEqual(proposal["summary"]["total_positions"], 2)
        self.assertEqual(proposal["summary"]["cash_anchor_positions"], 1)
        self.assertEqual(proposal["included"][0]["symbol"], "QQQI.US")
        self.assertEqual(proposal["excluded"][0]["symbol"], "NVDA.US")

    def test_sync_uses_fixed_readonly_command(self) -> None:
        positions_completed = type(
            "Completed",
            (),
            {
                "returncode": 0,
                "stdout": json.dumps(
                    [
                        {
                            "symbol": "XQQI.US",
                            "name": "XQQI",
                            "currency": "USD",
                            "quantity": "20",
                            "market": "US",
                            "available_quantity": "20",
                            "cost_price": "30",
                        }
                    ]
                ),
                "stderr": "",
            },
        )()
        quote_completed = type(
            "Completed",
            (),
            {
                "returncode": 0,
                "stdout": json.dumps(
                    [
                        {
                            "symbol": "XQQI.US",
                            "last": "53.560",
                            "pre_market_quote": {
                                "last": "53.795",
                                "timestamp": "2026-05-27T13:27:30Z",
                            },
                        }
                    ]
                ),
                "stderr": "",
            },
        )()
        with patch(
            "src.longbridge_provider.subprocess.run",
            side_effect=[positions_completed, quote_completed],
        ) as run:
            proposal = longbridge_provider.sync_longbridge_positions(timeout_seconds=3)

        self.assertEqual(run.call_count, 2)
        positions_args, positions_kwargs = run.call_args_list[0]
        quote_args, quote_kwargs = run.call_args_list[1]
        self.assertEqual(positions_args[0], ["longbridge", "positions", "--format", "json"])
        self.assertEqual(quote_args[0], ["longbridge", "quote", "XQQI.US", "--format", "json"])
        self.assertFalse(positions_kwargs.get("shell", False))
        self.assertFalse(quote_kwargs.get("shell", False))
        self.assertEqual(positions_kwargs["timeout"], 3)
        self.assertEqual(quote_kwargs["timeout"], 3)
        self.assertEqual(proposal["included"][0]["symbol"], "XQQI.US")
        self.assertEqual(proposal["included"][0]["current_price"], 53.795)

    def test_parse_quote_prefers_latest_extended_hours_price(self) -> None:
        payload = [
            {
                "symbol": "QQQI.US",
                "last": "56.850",
                "post_market_quote": {
                    "last": "56.840",
                    "timestamp": "2026-05-26T23:58:32Z",
                },
                "pre_market_quote": {
                    "last": "56.990",
                    "timestamp": "2026-05-27T13:28:20Z",
                },
            }
        ]

        quotes = longbridge_provider.parse_longbridge_quotes(payload)

        self.assertEqual(quotes[0].symbol, "QQQI.US")
        self.assertEqual(quotes[0].current_price, 56.99)
        self.assertEqual(quotes[0].quote_source, "pre_market_quote")

    def test_apply_cash_anchor_sync_preserves_existing_dividend_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _ledger_paths(Path(tmp))
            with patch.multiple(
                portfolio_ledger,
                DATA_DIR=paths["data"],
                TEMPLATE_DIR=paths["templates"],
                HOLDINGS_PATH=paths["holdings"],
                CAPITAL_FLOWS_PATH=paths["capital_flows"],
                PORTFOLIO_EVENTS_PATH=paths["portfolio_events"],
                DIVIDEND_PLAN_PATH=paths["dividend_plan"],
            ):
                portfolio_ledger.upsert_holding(
                    symbol="QQQI.US",
                    name="QQQI",
                    market="US",
                    currency="USD",
                    shares=1,
                    cost_price=40,
                    current_price=55,
                    annual_dividend_per_share=6,
                    tax_rate=0.3,
                )
                with patch("src.longbridge_provider.sync_longbridge_positions") as sync:
                    sync.return_value = {
                        "included": [
                            {
                                "symbol": "QQQI.US",
                                "name": "QQQI",
                                "market": "US",
                                "currency": "USD",
                                "quantity": 10,
                                "cost_price": 50,
                            }
                        ],
                        "excluded": [],
                        "summary": {"total_positions": 1, "cash_anchor_positions": 1, "excluded_positions": 0},
                    }
                    result = longbridge_provider.apply_longbridge_cash_anchor_sync()

                self.assertEqual(result["summary"]["updated_count"], 1)
                holdings = portfolio_ledger.read_holdings()
                self.assertEqual(holdings[0].shares, 10)
                self.assertEqual(holdings[0].cost_price, 50)
                self.assertEqual(holdings[0].current_price, 55)
                self.assertEqual(holdings[0].annual_dividend_per_share, 6)
                self.assertEqual(holdings[0].tax_rate, 0.3)
                events = portfolio_ledger.read_portfolio_events()
                self.assertEqual(events[-1].event_type, "sync_snapshot")

    def test_apply_cash_anchor_sync_preserves_longbridge_cost_precision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _ledger_paths(Path(tmp))
            with patch.multiple(
                portfolio_ledger,
                DATA_DIR=paths["data"],
                TEMPLATE_DIR=paths["templates"],
                HOLDINGS_PATH=paths["holdings"],
                CAPITAL_FLOWS_PATH=paths["capital_flows"],
                PORTFOLIO_EVENTS_PATH=paths["portfolio_events"],
                DIVIDEND_PLAN_PATH=paths["dividend_plan"],
            ):
                with patch("src.longbridge_provider.sync_longbridge_positions") as sync:
                    sync.return_value = {
                        "included": [
                            {
                                "symbol": "XQQI.US",
                                "name": "XQQI",
                                "market": "US",
                                "currency": "USD",
                                "quantity": 80,
                                "cost_price": 43.404,
                            }
                        ],
                        "excluded": [],
                        "summary": {"total_positions": 1, "cash_anchor_positions": 1, "excluded_positions": 0},
                    }
                    longbridge_provider.apply_longbridge_cash_anchor_sync()

                content = paths["holdings"].read_text(encoding="utf-8")
                self.assertIn("43.404", content)
                events = paths["portfolio_events"].read_text(encoding="utf-8")
                self.assertIn("43.404", events)


def _ledger_paths(root: Path) -> dict[str, Path]:
    data = root / "data"
    templates = root / "data_templates"
    templates.mkdir(parents=True)
    (templates / "dividend_plan.yaml").write_text(
        "\n".join(
            [
                "plan_name: Cash Anchor 10 Year Retirement Plan",
                "base_year: 2026",
                "retirement_years: 10",
                "annual_contribution_target: 50000",
                "currency: USD",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return {
        "data": data,
        "templates": templates,
        "holdings": data / "holdings.csv",
        "capital_flows": data / "capital_flows.csv",
        "portfolio_events": data / "portfolio_events.csv",
        "dividend_plan": data / "dividend_plan.yaml",
    }


if __name__ == "__main__":
    unittest.main()
