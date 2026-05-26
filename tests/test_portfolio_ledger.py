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

    def test_update_dividend_plan_changes_targets_and_keeps_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _ledger_paths(Path(tmp))
            with _patch_ledger_paths(paths):
                portfolio_ledger.record_capital_contribution(
                    amount=5000,
                    contribution_date=date(2026, 5, 24),
                )
                snapshot = portfolio_ledger.update_dividend_plan(
                    annual_contribution_target=60000,
                    target_annual_dividend=120000,
                    as_of=date(2026, 5, 24),
                )

                self.assertEqual(snapshot["plan"]["annual_contribution_target"], 60000)
                self.assertEqual(snapshot["plan"]["target_annual_dividend"], 120000)
                self.assertEqual(snapshot["summary"]["current_year_contribution"], 5000)
                self.assertEqual(snapshot["summary"]["annual_contribution_gap"], 55000)
                self.assertAlmostEqual(snapshot["summary"]["annual_contribution_progress"], 0.083333)

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
                "target_annual_dividend: 115000",
                "currency: CNY",
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


def _patch_ledger_paths(paths: dict[str, Path]):
    return patch.multiple(
        portfolio_ledger,
        DATA_DIR=paths["data"],
        TEMPLATE_DIR=paths["templates"],
        HOLDINGS_PATH=paths["holdings"],
        CAPITAL_FLOWS_PATH=paths["capital_flows"],
        PORTFOLIO_EVENTS_PATH=paths["portfolio_events"],
        DIVIDEND_PLAN_PATH=paths["dividend_plan"],
    )


if __name__ == "__main__":
    unittest.main()
