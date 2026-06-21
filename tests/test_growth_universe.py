from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src import growth_universe
from src.growth_universe import GrowthUniverseConfig, build_growth_universe_payload, option_underlying_symbol


class GrowthUniverseTest(unittest.TestCase):
    def test_option_symbol_maps_to_underlying(self) -> None:
        self.assertEqual(option_underlying_symbol("AVGO270617C500000.US"), "AVGO.US")
        self.assertEqual(option_underlying_symbol("BRKB270115C500000.US"), "BRKB.US")

    def test_build_universe_filters_and_merges_longbridge_sources(self) -> None:
        position_payload = {
            "source": "longbridge_cli",
            "scope": "growth_engine_us_positions",
            "positions": [
                {
                    "symbol": "NVDA.US",
                    "name": "NVIDIA",
                    "market": "US",
                    "currency": "USD",
                    "quantity": 2,
                    "available_quantity": 2,
                    "cost_price": 900,
                    "current_price": 950,
                },
                {
                    "symbol": "AVGO270617C500000.US",
                    "name": "AVGO Call",
                    "market": "US",
                    "currency": "USD",
                    "quantity": 1,
                    "cost_price": 20,
                },
            ],
            "excluded_cash_anchor": [
                {"symbol": "QQQI.US", "name": "QQQI", "market": "US", "currency": "USD"},
            ],
            "summary": {"ignored_non_us_positions": 0},
            "write_policy": "read_only_context",
        }
        watchlist_payload = {
            "source": "longbridge_cli",
            "scope": "classified_watchlist",
            "growth_us_watchlist": [
                {
                    "symbol": "NVDA.US",
                    "name": "NVIDIA",
                    "market": "US",
                    "group_name": "AI",
                    "is_pinned": True,
                },
                {
                    "symbol": "DRAM.US",
                    "name": "Roundhill Memory ETF",
                    "market": "US",
                    "group_name": "ETF",
                },
                {
                    "symbol": "UVIX.US",
                    "name": "2x Long VIX Futures ETF",
                    "market": "US",
                    "group_name": "ETF",
                },
                {
                    "symbol": "TSLL.US",
                    "name": "Direxion Daily TSLA Bull 2X Shares",
                    "market": "US",
                    "group_name": "ETF",
                },
                {
                    "symbol": "CONL260618C20000.US",
                    "name": "CONL 260618 20 Call",
                    "market": "US",
                    "group_name": "Options",
                },
                {
                    "symbol": ".NDX.US",
                    "name": "NASDAQ 100 Index",
                    "market": "US",
                    "group_name": "Index",
                },
            ],
            "cash_anchor_us_watchlist": [
                {"symbol": "TQQQ.US", "name": "TQQQ", "market": "US", "group_name": "Cash"},
            ],
            "ignored_non_us": [],
            "summary": {"ignored_non_us_watch_items": 0},
            "write_policy": "read_only_context",
        }

        payload = build_growth_universe_payload(position_payload, watchlist_payload)
        symbols = {item["symbol"]: item for item in payload["universe"]}
        excluded_reasons = {item["source_symbol"]: item["reason"] for item in payload["excluded"]}

        self.assertEqual(set(symbols), {"NVDA.US", "AVGO.US", "DRAM.US"})
        self.assertTrue(symbols["NVDA.US"]["has_position"])
        self.assertTrue(symbols["NVDA.US"]["is_pinned"])
        self.assertEqual(symbols["DRAM.US"]["asset_type"], "etf")
        self.assertIn("longbridge_position_option_underlying", symbols["AVGO.US"]["source_types"])
        self.assertEqual(excluded_reasons["QQQI.US"], "cash_anchor_symbol")
        self.assertEqual(excluded_reasons["TQQQ.US"], "cash_anchor_symbol")
        self.assertEqual(excluded_reasons["UVIX.US"], "leveraged_etf")
        self.assertEqual(excluded_reasons["TSLL.US"], "leveraged_etf")
        self.assertTrue(
            any(
                item["source_symbol"] == "CONL260618C20000.US"
                and item["reason"] == "option_contract_mapped_to_underlying"
                for item in payload["excluded"]
            )
        )
        self.assertTrue(
            any(
                item["source_symbol"] == "CONL260618C20000.US"
                and item["normalized_symbol"] == "CONL.US"
                and item["reason"] == "leveraged_etf"
                for item in payload["excluded"]
            )
        )
        self.assertEqual(excluded_reasons[".NDX.US"], "index_not_investable")
        self.assertEqual(excluded_reasons["AVGO270617C500000.US"], "option_contract_mapped_to_underlying")
        self.assertEqual(payload["summary"]["universe_count"], 3)
        self.assertEqual(payload["summary"]["ordinary_etf_count"], 1)
        self.assertEqual(payload["summary"]["option_contracts_mapped"], 2)

    def test_special_etf_and_allowlist_classification(self) -> None:
        payload = build_growth_universe_payload(
            {"positions": [], "summary": {}},
            {
                "growth_us_watchlist": [
                    {
                        "symbol": "SPCX.US",
                        "name": "The SPAC and New Issue ETF",
                        "market": "US",
                    },
                    {
                        "symbol": "FAKE.US",
                        "name": "2x Robotics ETF",
                        "market": "US",
                    },
                ],
                "summary": {},
            },
            config=GrowthUniverseConfig(
                leveraged_etf_allowlist={"FAKE"},
                ordinary_etf_allowlist={"SPCX", "FAKE"},
                special_etf_classifications={
                    "SPCX": {"asset_subtype": "spac_new_issue_etf", "notes": "普通 SPAC ETF"}
                },
            ),
        )

        symbols = {item["symbol"]: item for item in payload["universe"]}

        self.assertEqual(symbols["SPCX.US"]["asset_type"], "etf")
        self.assertEqual(symbols["SPCX.US"]["asset_subtype"], "spac_new_issue_etf")
        self.assertIn("special_etf", symbols["SPCX.US"]["classification_tags"])
        self.assertEqual(symbols["FAKE.US"]["asset_type"], "etf")
        self.assertEqual(symbols["FAKE.US"]["asset_subtype"], "ordinary_etf")
        self.assertEqual(payload["summary"]["special_etf_count"], 1)

    def test_configured_blocklist_excludes_symbol(self) -> None:
        payload = build_growth_universe_payload(
            {"positions": [], "summary": {}},
            {
                "growth_us_watchlist": [
                    {
                        "symbol": "SPCX.US",
                        "name": "The SPAC and New Issue ETF",
                        "market": "US",
                    }
                ],
                "summary": {},
            },
            config=GrowthUniverseConfig(leveraged_etf_blocklist={"SPCX"}),
        )

        self.assertFalse(payload["universe"])
        self.assertEqual(payload["excluded"][0]["reason"], "leveraged_etf")

    def test_sync_growth_universe_uses_valid_cache(self) -> None:
        with TemporaryDirectory() as tmp:
            runtime_root = Path(tmp)
            with patch.object(growth_universe, "RUNTIME_DIR", runtime_root), patch.object(
                growth_universe, "sync_longbridge_growth_positions"
            ) as sync_positions, patch.object(growth_universe, "sync_longbridge_watchlist") as sync_watchlist:
                sync_positions.return_value = {
                    "positions": [
                        {"symbol": "NVDA.US", "name": "NVIDIA", "market": "US", "currency": "USD"},
                    ],
                    "summary": {},
                }
                sync_watchlist.return_value = {"growth_us_watchlist": [], "summary": {}}

                first = growth_universe.sync_growth_universe(refresh=True)
                second = growth_universe.sync_growth_universe()

        self.assertFalse(first["cache"]["hit"])
        self.assertTrue(second["cache"]["hit"])
        self.assertEqual(sync_positions.call_count, 1)
        self.assertEqual(sync_watchlist.call_count, 1)


if __name__ == "__main__":
    unittest.main()
