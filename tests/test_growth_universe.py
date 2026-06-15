from __future__ import annotations

import unittest

from src.growth_universe import build_growth_universe_payload, option_underlying_symbol


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


if __name__ == "__main__":
    unittest.main()
