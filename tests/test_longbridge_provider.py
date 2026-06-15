from __future__ import annotations

import json
import unittest
import tempfile
from datetime import date
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

    def test_build_growth_us_payload_excludes_cash_anchor_symbols(self) -> None:
        positions = [
            longbridge_provider.LongbridgePosition(
                symbol="QQQI.US",
                name="QQQI",
                market="US",
                currency="USD",
                quantity=10,
                available_quantity=10,
                cost_price=50,
            ),
            longbridge_provider.LongbridgePosition(
                symbol="NVDA.US",
                name="NVIDIA",
                market="US",
                currency="USD",
                quantity=2,
                available_quantity=2,
                cost_price=900,
            ),
            longbridge_provider.LongbridgePosition(
                symbol="AAPL.US",
                name="Apple",
                market="US",
                currency="USD",
                quantity=1,
                available_quantity=1,
                cost_price=180,
            ),
        ]

        payload = longbridge_provider.build_growth_engine_us_positions_payload(positions)

        self.assertEqual(payload["summary"]["growth_us_positions"], 2)
        self.assertEqual(payload["summary"]["cash_anchor_us_positions"], 1)
        self.assertEqual([item["symbol"] for item in payload["positions"]], ["NVDA.US", "AAPL.US"])
        self.assertEqual(payload["positions"][0]["sub_framework"], "US_Disruptive_Growth")
        self.assertEqual(payload["write_policy"], "read_only_context")

    def test_parse_and_classify_longbridge_watchlist(self) -> None:
        payload = [
            {
                "id": 1,
                "name": "all",
                "securities": [
                    {"symbol": "QQQI.US", "name": "QQQI", "market": "US", "is_pinned": True},
                    {"symbol": "NVDA.US", "name": "NVIDIA", "market": "US", "is_pinned": False},
                    {"symbol": "ETHUSD.HAS", "name": "ETH/USD", "market": "Unknown", "is_pinned": True},
                ],
            },
            {
                "id": 2,
                "name": "us",
                "securities": [
                    {"symbol": "NVDA.US", "name": "NVIDIA", "market": "US", "is_pinned": True},
                ],
            },
        ]

        items = longbridge_provider.parse_longbridge_watchlist(payload)
        classified = longbridge_provider.build_longbridge_watchlist_payload(items)

        self.assertEqual(classified["summary"]["total_watch_items"], 3)
        self.assertEqual(classified["summary"]["cash_anchor_us_watch_items"], 1)
        self.assertEqual(classified["summary"]["growth_us_watch_items"], 1)
        self.assertEqual(classified["summary"]["ignored_non_us_watch_items"], 1)
        self.assertEqual(classified["cash_anchor_us_watchlist"][0]["symbol"], "QQQI.US")
        self.assertEqual(classified["growth_us_watchlist"][0]["symbol"], "NVDA.US")
        self.assertTrue(classified["growth_us_watchlist"][0]["is_pinned"])
        self.assertIn("all", classified["growth_us_watchlist"][0]["group_name"])
        self.assertIn("us", classified["growth_us_watchlist"][0]["group_name"])

    def test_sync_watchlist_uses_fixed_readonly_command(self) -> None:
        completed = type(
            "Completed",
            (),
            {
                "returncode": 0,
                "stdout": json.dumps(
                    [
                        {
                            "id": 1,
                            "name": "us",
                            "securities": [
                                {"symbol": "QQQI.US", "name": "QQQI", "market": "US"},
                                {"symbol": "NVDA.US", "name": "NVIDIA", "market": "US"},
                            ],
                        }
                    ]
                ),
                "stderr": "",
            },
        )()
        with patch("src.longbridge_provider.subprocess.run", return_value=completed) as run:
            payload = longbridge_provider.sync_longbridge_watchlist(timeout_seconds=3)

        self.assertEqual(run.call_args.args[0], ["longbridge", "watchlist", "--format", "json"])
        self.assertFalse(run.call_args.kwargs.get("shell", False))
        self.assertEqual(run.call_args.kwargs["timeout"], 3)
        self.assertEqual(payload["summary"]["growth_us_watch_items"], 1)

    def test_sync_growth_positions_uses_fixed_readonly_commands(self) -> None:
        positions_completed = type(
            "Completed",
            (),
            {
                "returncode": 0,
                "stdout": json.dumps(
                    [
                        {
                            "symbol": "QQQI.US",
                            "name": "QQQI",
                            "currency": "USD",
                            "quantity": "20",
                            "market": "US",
                            "available_quantity": "20",
                            "cost_price": "50",
                        },
                        {
                            "symbol": "NVDA.US",
                            "name": "NVIDIA",
                            "currency": "USD",
                            "quantity": "3",
                            "market": "US",
                            "available_quantity": "3",
                            "cost_price": "900",
                        },
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
                "stdout": json.dumps([{"symbol": "NVDA.US", "last": "950"}]),
                "stderr": "",
            },
        )()
        with patch("src.longbridge_provider.subprocess.run", side_effect=[positions_completed, quote_completed]) as run:
            payload = longbridge_provider.sync_longbridge_growth_positions(timeout_seconds=3)

        self.assertEqual(run.call_args_list[0].args[0], ["longbridge", "positions", "--format", "json"])
        self.assertEqual(run.call_args_list[1].args[0], ["longbridge", "quote", "NVDA.US", "--format", "json"])
        self.assertEqual(payload["positions"][0]["symbol"], "NVDA.US")
        self.assertEqual(payload["positions"][0]["current_price"], 950)

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

    def test_parse_cash_flow_filters_dividend_income(self) -> None:
        payload = {
            "code": 0,
            "data": {
                "list": [
                    {
                        "transaction_flow_name": "Dividend",
                        "direction": "2",
                        "balance": "12.34",
                        "currency": "USD",
                        "business_time": "2026-05-29",
                        "symbol": "QQQI.US",
                        "description": "QQQI distribution",
                    },
                    {
                        "transaction_flow_name": "BuyContract-Stocks",
                        "direction": "1",
                        "balance": "-100",
                        "currency": "USD",
                        "business_time": "2026-05-29",
                        "symbol": "QQQI.US",
                    },
                ]
            },
        }

        flows = longbridge_provider.parse_longbridge_cash_flows(payload)
        dividends = longbridge_provider.filter_dividend_cash_flows(flows, ["QQQI.US"])

        self.assertEqual(len(dividends), 1)
        self.assertEqual(dividends[0].symbol, "QQQI.US")
        self.assertEqual(dividends[0].event_date, date(2026, 5, 29))

    def test_parse_dividend_history_extracts_per_share_amount(self) -> None:
        payload = [
            {
                "symbol": "QQQI.US",
                "desc": "Dividend: USD 0.615/share",
                "ex_date": "2026.05.20",
                "payment_date": "2026.05.28",
                "record_date": "2026.05.21",
            },
            {
                "symbol": "QQQI.US",
                "desc": "Split event",
            },
        ]

        records = longbridge_provider.parse_longbridge_dividend_history(payload, symbol="QQQI.US")

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].amount_per_share, 0.615)
        self.assertEqual(records[0].currency, "USD")
        self.assertEqual(records[0].payment_date, "2026-05-28")

    def test_parse_exchange_rates(self) -> None:
        payload = {
            "exchanges": [
                {
                    "base_currency": "USD",
                    "other_currency": "CNY",
                    "average_rate": 0.14787,
                    "bid_rate": 0.1478,
                    "offer_rate": 0.1479,
                }
            ]
        }

        rates = longbridge_provider.parse_longbridge_exchange_rates(payload)

        self.assertEqual(len(rates), 1)
        self.assertEqual(rates[0].base_currency, "USD")
        self.assertEqual(rates[0].other_currency, "CNY")
        self.assertEqual(rates[0].average_rate, 0.14787)

    def test_us_income_sync_uses_fixed_commands_and_writes_ledger(self) -> None:
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
                US_DISTRIBUTION_HISTORY_PATH=paths["us_distribution_history"],
            ):
                portfolio_ledger.upsert_holding(
                    symbol="QQQI.US",
                    name="QQQI",
                    market="US",
                    currency="USD",
                    shares=100,
                    cost_price=50,
                    current_price=55,
                    annual_dividend_per_share=0,
                    tax_rate=0,
                )
                cash_flow_completed = type(
                    "Completed",
                    (),
                    {
                        "returncode": 0,
                        "stdout": json.dumps(
                            {
                                "data": {
                                    "list": [
                                        {
                                            "transaction_flow_name": "Dividend",
                                            "direction": "2",
                                            "balance": "61.50",
                                            "currency": "USD",
                                            "business_time": "2026-05-29",
                                            "symbol": "QQQI.US",
                                            "description": "QQQI distribution",
                                        }
                                    ]
                                }
                            }
                        ),
                        "stderr": "",
                    },
                )()
                dividend_completed = type(
                    "Completed",
                    (),
                    {
                        "returncode": 0,
                        "stdout": json.dumps(
                            [
                                {
                                    "symbol": "QQQI.US",
                                    "desc": "Dividend: USD 0.615/share",
                                    "ex_date": "2026-05-20",
                                    "payment_date": "2026-05-28",
                                    "record_date": "2026-05-21",
                                }
                            ]
                        ),
                        "stderr": "",
                    },
                )()
                with patch("src.longbridge_provider.subprocess.run", side_effect=[cash_flow_completed, dividend_completed]) as run:
                    result = longbridge_provider.sync_longbridge_us_income_distributions(
                        start=date(2026, 1, 1),
                        end=date(2026, 6, 4),
                    )

                first_args = run.call_args_list[0].args[0]
                second_args = run.call_args_list[1].args[0]
                self.assertEqual(
                    first_args,
                    ["longbridge", "cash-flow", "--start", "2026-01-01", "--end", "2026-06-04", "--format", "json"],
                )
                self.assertEqual(second_args, ["longbridge", "dividend", "QQQI.US", "--format", "json"])
                self.assertEqual(result["cash_flow_import"]["created_count"], 1)
                self.assertEqual(result["history_import"]["created_count"], 1)
                self.assertEqual(portfolio_ledger.read_portfolio_events()[0].source, "longbridge_cash_flow")
                self.assertEqual(portfolio_ledger.read_us_distribution_history()[0].amount_per_share, 0.615)

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
                US_DISTRIBUTION_HISTORY_PATH=paths["us_distribution_history"],
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
                US_DISTRIBUTION_HISTORY_PATH=paths["us_distribution_history"],
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
        "us_distribution_history": data / "us_distribution_history.csv",
    }


if __name__ == "__main__":
    unittest.main()
