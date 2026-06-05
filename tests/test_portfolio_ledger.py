from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from src import portfolio_ledger


class PortfolioLedgerTest(unittest.TestCase):
    def test_record_contribution_initializes_files_and_reports_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _ledger_paths(Path(tmp))
            with _patch_ledger_paths(paths):
                result = portfolio_ledger.record_capital_contribution(
                    amount=5000,
                    contribution_date=date(2026, 5, 24),
                    notes="A股红利池月度工资投入",
                )

                self.assertEqual(result["current_year_contribution"], 5000)
                self.assertEqual(result["annual_contribution_target"], 50000)
                self.assertEqual(result["annual_contribution_gap"], 45000)
                self.assertEqual(result["annual_contribution_progress"], 0.1)
                self.assertTrue(paths["capital_flows"].exists())
                self.assertIn("2026-05-24,5000,CNY,salary", paths["capital_flows"].read_text())

    def test_update_dividend_plan_changes_contribution_target_and_keeps_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _ledger_paths(Path(tmp))
            with _patch_ledger_paths(paths):
                portfolio_ledger.record_capital_contribution(
                    amount=5000,
                    contribution_date=date(2026, 5, 24),
                )
                snapshot = portfolio_ledger.update_dividend_plan(
                    annual_contribution_target=60000,
                    as_of=date(2026, 5, 24),
                )

                self.assertEqual(snapshot["plan"]["annual_contribution_target"], 60000)
                self.assertEqual(snapshot["summary"]["current_year_contribution"], 5000)
                self.assertEqual(snapshot["summary"]["annual_contribution_gap"], 55000)
                self.assertAlmostEqual(snapshot["summary"]["annual_contribution_progress"], 0.083333)
                self.assertNotIn("target_annual_dividend", snapshot["plan"])
                self.assertEqual(snapshot["plan"]["core_position_limit_pct"], 0.15)
                self.assertEqual(snapshot["plan"]["industry_limit_pct"]["utility"], 0.30)

    def test_negative_targets_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _ledger_paths(Path(tmp))
            with _patch_ledger_paths(paths):
                with self.assertRaises(ValueError):
                    portfolio_ledger.update_dividend_plan(annual_contribution_target=-1)

    def test_upsert_holding_creates_and_updates_position(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _ledger_paths(Path(tmp))
            with _patch_ledger_paths(paths):
                created = portfolio_ledger.upsert_holding(
                    symbol="600000",
                    name="示例银行",
                    shares=1000,
                    cost_price=10,
                    current_price=10.5,
                    annual_dividend_per_share=0.4,
                    tax_rate=0,
                    as_of=date(2026, 5, 24),
                )

                self.assertEqual(created["holding_action"], "created")
                self.assertEqual(created["summary"]["net_annual_dividend"], 400)
                self.assertTrue(paths["holdings"].exists())

                updated = portfolio_ledger.upsert_holding(
                    symbol="600000",
                    name="示例银行",
                    shares=2000,
                    cost_price=10,
                    current_price=11,
                    annual_dividend_per_share=0.5,
                    tax_rate=0.1,
                    as_of=date(2026, 5, 24),
                )

                self.assertEqual(updated["holding_action"], "updated")
                self.assertEqual(updated["summary"]["net_annual_dividend"], 900)
                rows = paths["holdings"].read_text(encoding="utf-8").splitlines()
                self.assertEqual(len(rows), 2)

    def test_buy_sell_and_dividend_events_update_local_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _ledger_paths(Path(tmp))
            with _patch_ledger_paths(paths):
                bought = portfolio_ledger.record_buy(
                    symbol="600000",
                    name="示例银行",
                    shares=1000,
                    price=8,
                    trade_date=date(2026, 5, 25),
                    annual_dividend_per_share=0.4,
                )
                bought = portfolio_ledger.record_buy(
                    symbol="600000",
                    shares=1000,
                    price=10,
                    trade_date=date(2026, 5, 26),
                )

                self.assertEqual(bought["updated_holding"]["shares"], 2000)
                self.assertEqual(bought["updated_holding"]["cost_price"], 9)
                self.assertEqual(bought["summary"]["net_annual_dividend"], 800)

                sold = portfolio_ledger.record_sell(
                    symbol="600000",
                    shares=500,
                    price=11,
                    trade_date=date(2026, 5, 27),
                )
                self.assertEqual(sold["remaining_shares"], 1500)
                self.assertEqual(sold["summary"]["net_annual_dividend"], 600)

                dividend = portfolio_ledger.record_dividend(
                    symbol="600000",
                    amount=300,
                    dividend_date=date(2026, 6, 20),
                )
                self.assertEqual(dividend["amount"], 300)
                events = portfolio_ledger.read_portfolio_events()
                self.assertEqual([item.event_type for item in events], ["buy", "buy", "sell", "dividend"])
                self.assertTrue(paths["portfolio_events"].exists())

    def test_snapshot_separates_received_dividends_from_forecast_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _ledger_paths(Path(tmp))
            with _patch_ledger_paths(paths):
                portfolio_ledger.upsert_holding(
                    symbol="600900.SH",
                    name="长江电力",
                    shares=1000,
                    cost_price=24,
                    current_price=24,
                    annual_dividend_per_share=0,
                    tax_rate=0,
                    as_of=date(2026, 5, 24),
                    notes="current_price=pending_quote",
                )
                portfolio_ledger.record_dividend(
                    symbol="600900.SH",
                    amount=300,
                    dividend_date=date(2026, 6, 20),
                )

                snapshot = portfolio_ledger.build_portfolio_snapshot(as_of=date(2026, 6, 21))

        self.assertEqual(snapshot["summary"]["current_year_dividend_received"], 300)
        self.assertEqual(snapshot["summary"]["current_year_dividend_received_by_currency"], [{"currency": "CNY", "amount": 300}])
        self.assertEqual(snapshot["dividend_analysis"]["status"], "partial")
        self.assertEqual(snapshot["dividend_analysis"]["current_year_received"]["event_count"], 1)
        self.assertEqual(snapshot["dividend_analysis"]["forecast_from_holdings"]["missing_position_count"], 1)
        self.assertIn("/dividend", "\n".join(snapshot["dividend_analysis"]["repair_actions"]))
        self.assertEqual(snapshot["data_quality"]["pending_quote_symbols"][0]["symbol"], "600900.SH")

    def test_snapshot_reports_mixed_currency_and_duplicate_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _ledger_paths(Path(tmp))
            with _patch_ledger_paths(paths):
                portfolio_ledger.upsert_holding(
                    symbol="QQQI.US",
                    name="QQQI",
                    market="US",
                    currency="USD",
                    shares=10,
                    cost_price=50,
                    current_price=55,
                    annual_dividend_per_share=1,
                    tax_rate=0,
                    as_of=date(2026, 5, 24),
                )
                portfolio_ledger.upsert_holding(
                    symbol="600132.SH",
                    name="重庆啤酒",
                    market="A股",
                    currency="CNY",
                    shares=100,
                    cost_price=70,
                    current_price=70,
                    annual_dividend_per_share=0,
                    tax_rate=0,
                    as_of=date(2026, 5, 24),
                )
                snapshot = portfolio_ledger.upsert_holding(
                    symbol="600132",
                    name="重庆啤酒",
                    market="A股",
                    currency="CNY",
                    shares=200,
                    cost_price=52,
                    current_price=52,
                    annual_dividend_per_share=0,
                    tax_rate=0,
                    as_of=date(2026, 5, 24),
                )

        self.assertEqual(snapshot["summary"]["currency_scope"], "mixed")
        self.assertTrue(snapshot["currency_breakdown"]["is_mixed_currency"])
        groups = {(item["market"], item["currency"]) for item in snapshot["market_breakdown"]["groups"]}
        self.assertIn(("A股", "CNY"), groups)
        self.assertIn(("US", "USD"), groups)
        duplicates = snapshot["data_quality"]["duplicate_symbol_groups"]
        self.assertEqual(duplicates[0]["canonical_symbol"], "600132")
        self.assertIn("不能把成本", "\n".join(snapshot["data_quality"]["warnings"]))

    def test_snapshot_builds_position_limit_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _ledger_paths(Path(tmp))
            with _patch_ledger_paths(paths):
                portfolio_ledger.upsert_holding(
                    symbol="600900",
                    name="长江电力",
                    market="A股",
                    currency="CNY",
                    shares=1000,
                    cost_price=15,
                    current_price=15,
                    annual_dividend_per_share=1,
                    tax_rate=0,
                    as_of=date(2026, 5, 24),
                )
                snapshot = portfolio_ledger.upsert_holding(
                    symbol="600036",
                    name="招商银行",
                    market="A股",
                    currency="CNY",
                    shares=1000,
                    cost_price=5,
                    current_price=5,
                    annual_dividend_per_share=1,
                    tax_rate=0,
                    as_of=date(2026, 5, 24),
                )

        analysis = snapshot["position_limit_analysis"]
        self.assertEqual(analysis["status"], "over_limit")
        position = {item["symbol"]: item for item in analysis["positions"]}["600900"]
        self.assertEqual(position["limit_type"], "core")
        self.assertAlmostEqual(position["weight"], 0.75)
        self.assertEqual(position["limit_pct"], 0.15)
        self.assertFalse(position["can_add"])
        industry = {item["industry"]: item for item in analysis["industries"]}["utility"]
        self.assertEqual(industry["status"], "over_limit")
        self.assertIn("仓位纪律发现超限", "\n".join(snapshot["data_quality"]["warnings"]))
        self.assertIn("仓位纪律：已超限", portfolio_ledger.format_snapshot(snapshot))

    def test_resource_industry_defaults_to_cyclical_single_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _ledger_paths(Path(tmp))
            with _patch_ledger_paths(paths):
                snapshot = portfolio_ledger.upsert_holding(
                    symbol="601088",
                    name="中国神华煤炭",
                    market="A股",
                    currency="CNY",
                    shares=1000,
                    cost_price=20,
                    current_price=20,
                    annual_dividend_per_share=1,
                    tax_rate=0,
                    as_of=date(2026, 5, 24),
                )

        position = snapshot["position_limit_analysis"]["positions"][0]
        self.assertEqual(position["industry"], "resource")
        self.assertEqual(position["limit_type"], "cyclical")
        self.assertEqual(position["limit_pct"], 0.08)

    def test_snapshot_builds_us_income_distribution_forecast(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _ledger_paths(Path(tmp))
            with _patch_ledger_paths(paths):
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
                    as_of=date(2026, 1, 2),
                )
                portfolio_ledger.upsert_us_distribution_history(
                    [
                        portfolio_ledger.USDistributionRecord(
                            symbol="QQQI.US",
                            ex_date="2026-03-20",
                            payment_date="2026-03-28",
                            record_date="2026-03-21",
                            amount_per_share=0.6,
                            currency="USD",
                            source="longbridge_dividend_history",
                            notes="Dividend: USD 0.6/share",
                        ),
                        portfolio_ledger.USDistributionRecord(
                            symbol="QQQI.US",
                            ex_date="2026-04-20",
                            payment_date="2026-04-28",
                            record_date="2026-04-21",
                            amount_per_share=0.7,
                            currency="USD",
                            source="longbridge_dividend_history",
                            notes="Dividend: USD 0.7/share",
                        ),
                        portfolio_ledger.USDistributionRecord(
                            symbol="QQQI.US",
                            ex_date="2026-05-20",
                            payment_date="2026-05-28",
                            record_date="2026-05-21",
                            amount_per_share=0.8,
                            currency="USD",
                            source="longbridge_dividend_history",
                            notes="Dividend: USD 0.8/share",
                        ),
                    ]
                )

                snapshot = portfolio_ledger.build_portfolio_snapshot(as_of=date(2026, 6, 4))

        forecast = snapshot["dividend_analysis"]["us_income_distribution_forecast"]
        self.assertEqual(forecast["positions"][0]["symbol"], "QQQI.US")
        self.assertEqual(forecast["positions"][0]["trailing_3m"]["record_count"], 3)
        self.assertGreater(forecast["positions"][0]["trailing_3m"]["estimated_annual_cash"], 800)
        self.assertIn("滚动预测", forecast["policy"])
        estimate = snapshot["dividend_analysis"]["portfolio_dividend_yield_estimate"]
        self.assertEqual(estimate["positions"][0]["selected_window"], "trailing_6m")
        self.assertEqual(estimate["portfolio_total"]["status"], "ok")
        self.assertGreater(estimate["portfolio_total"]["current_yield"], 0.07)

    def test_dividend_yield_estimate_separates_a_share_and_us_income(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _ledger_paths(Path(tmp))
            with _patch_ledger_paths(paths):
                portfolio_ledger.upsert_holding(
                    symbol="600900",
                    name="长江电力",
                    market="A股",
                    currency="CNY",
                    shares=1000,
                    cost_price=25,
                    current_price=25,
                    annual_dividend_per_share=1,
                    tax_rate=0,
                    as_of=date(2026, 1, 2),
                )
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
                    as_of=date(2026, 1, 2),
                )
                portfolio_ledger.upsert_us_distribution_history(
                    [
                        portfolio_ledger.USDistributionRecord(
                            symbol="QQQI.US",
                            ex_date="2026-03-20",
                            payment_date="2026-03-28",
                            record_date="2026-03-21",
                            amount_per_share=0.6,
                            currency="USD",
                            source="longbridge_dividend_history",
                        ),
                        portfolio_ledger.USDistributionRecord(
                            symbol="QQQI.US",
                            ex_date="2026-04-20",
                            payment_date="2026-04-28",
                            record_date="2026-04-21",
                            amount_per_share=0.7,
                            currency="USD",
                            source="longbridge_dividend_history",
                        ),
                        portfolio_ledger.USDistributionRecord(
                            symbol="QQQI.US",
                            ex_date="2026-05-20",
                            payment_date="2026-05-28",
                            record_date="2026-05-21",
                            amount_per_share=0.8,
                            currency="USD",
                            source="longbridge_dividend_history",
                        ),
                    ]
                )

                snapshot = portfolio_ledger.build_portfolio_snapshot(as_of=date(2026, 6, 4))

        estimate = snapshot["dividend_analysis"]["portfolio_dividend_yield_estimate"]
        groups = {(item["market"], item["currency"]): item for item in estimate["by_market"]}
        self.assertIn(("A股", "CNY"), groups)
        self.assertIn(("US", "USD"), groups)
        self.assertAlmostEqual(groups[("A股", "CNY")]["current_yield"], 0.04)
        self.assertGreater(groups[("US", "USD")]["current_yield"], 0.07)
        self.assertEqual(estimate["portfolio_total"]["status"], "requires_fx")
        estimate_with_fx = portfolio_ledger._build_portfolio_dividend_yield_estimate(
            snapshot["positions"],
            snapshot["dividend_analysis"]["us_income_distribution_forecast"],
            base_currency="CNY",
            fx_rates=[
                {
                    "base_currency": "USD",
                    "other_currency": "CNY",
                    "average_rate": 0.14787,
                }
            ],
            fx_source="longbridge_exchange_rate",
        )
        self.assertEqual(estimate_with_fx["portfolio_total"]["status"], "ok")
        self.assertEqual(estimate_with_fx["portfolio_total"]["currency"], "CNY")
        self.assertGreater(estimate_with_fx["portfolio_total"]["current_yield"], 0.04)

    def test_enriched_portfolio_snapshot_attaches_market_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _ledger_paths(Path(tmp))
            with _patch_ledger_paths(paths):
                portfolio_ledger.upsert_holding(
                    symbol="600900.SH",
                    name="长江电力",
                    shares=1000,
                    cost_price=24,
                    current_price=24,
                    annual_dividend_per_share=1,
                    tax_rate=0,
                    as_of=date(2026, 5, 24),
                    notes="current_price=pending_quote",
                )
                before = paths["holdings"].read_text(encoding="utf-8")
                with patch("src.market_data.provider_router.fetch_quote") as fetch_quote:
                    fetch_quote.return_value.to_dict.return_value = {
                        "status": "ok",
                        "source": "yfinance",
                        "market": "CN",
                        "symbol": "600900.SH",
                        "data": {"current_price": 28.5, "annual_dividend_per_share": 0.82},
                        "error": "",
                    }
                    snapshot = portfolio_ledger.build_enriched_portfolio_snapshot(as_of=date(2026, 5, 24))
                after = paths["holdings"].read_text(encoding="utf-8")

        self.assertEqual(snapshot["market_data"]["600900.SH"]["source"], "yfinance")
        self.assertEqual(snapshot["market_data_summary"]["status_counts"], {"ok": 1})
        self.assertNotIn("annual_dividend_per_share", snapshot["market_data"]["600900.SH"]["data"])
        self.assertEqual(snapshot["market_data"]["600900.SH"]["data"]["cashflow_dividend_usable"], False)
        self.assertIn("annual_dividend_per_share", snapshot["market_data"]["600900.SH"]["data"]["ignored_dividend_fields"])
        self.assertIn("持仓账本", snapshot["market_data_policy"]["failure_policy"])
        self.assertIn("利润分配公告", snapshot["market_data_policy"]["cashflow_dividend_policy"])
        estimate = snapshot["dividend_analysis"]["portfolio_dividend_yield_estimate"]
        group = estimate["by_market"][0]
        self.assertEqual(group["market_value"], 28500)
        self.assertAlmostEqual(group["current_yield"], 1000 / 28500, places=6)
        self.assertEqual(before, after)
        fetch_quote.assert_called_once_with("600900.SH", market="A股")


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
                "currency: CNY",
                "limit_single_core_pct: 0.15",
                "limit_single_normal_pct: 0.10",
                "limit_single_cyclical_pct: 0.08",
                "limit_cyclical_total_pct: 0.25",
                "limit_industry_default_pct: 0.30",
                "limit_industry_bank_pct: 0.30",
                "limit_industry_insurance_pct: 0.15",
                "limit_industry_resource_pct: 0.20",
                "limit_industry_utility_pct: 0.30",
                "limit_industry_telecom_pct: 0.20",
                "limit_industry_transport_pct: 0.15",
                "limit_industry_consumer_pct: 0.20",
                "limit_cyclical_industries: resource,coal,shipping,nonferrous",
                "limit_symbol_types: 000333=normal,600036=core,600132=normal,600795=normal,600887=normal,600900=core,600941=core,601166=normal,601318=normal,601985=normal",
                "limit_symbol_industries: 000333=consumer,600036=bank,600132=consumer,600795=utility,600887=consumer,600900=utility,600941=telecom,601166=bank,601318=insurance,601985=utility",
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


def _patch_ledger_paths(paths: dict[str, Path]):
    return patch.multiple(
        portfolio_ledger,
        DATA_DIR=paths["data"],
        TEMPLATE_DIR=paths["templates"],
        HOLDINGS_PATH=paths["holdings"],
        CAPITAL_FLOWS_PATH=paths["capital_flows"],
        PORTFOLIO_EVENTS_PATH=paths["portfolio_events"],
        DIVIDEND_PLAN_PATH=paths["dividend_plan"],
        US_DISTRIBUTION_HISTORY_PATH=paths["us_distribution_history"],
    )


if __name__ == "__main__":
    unittest.main()
