from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import growth_portfolio


class GrowthPortfolioTest(unittest.TestCase):
    def test_upsert_growth_holding_and_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _growth_paths(Path(tmp))
            with _patch_growth_paths(paths):
                result = growth_portfolio.upsert_growth_holding(
                    symbol="NVDA.US",
                    name="NVIDIA",
                    market="US",
                    shares=10,
                    cost_price=800,
                    current_price=950,
                    position_type="核心仓",
                    thesis="AI 算力平台",
                )
                snapshot = growth_portfolio.build_growth_snapshot(market="US")

        self.assertEqual(result["holding_action"], "created")
        self.assertEqual(snapshot["summary"]["holding_count"], 1)
        self.assertEqual(snapshot["summary"]["total_cost"], 8000)
        self.assertEqual(snapshot["summary"]["total_market_value"], 9500)
        self.assertEqual(snapshot["holdings"][0]["sub_framework"], "US_Disruptive_Growth")

    def test_review_growth_symbol_calls_llm_with_local_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _growth_paths(Path(tmp))
            with _patch_growth_paths(paths):
                growth_portfolio.upsert_growth_holding(
                    symbol="300750.SZ",
                    name="宁德时代",
                    market="CN",
                    shares=100,
                    cost_price=200,
                    current_price=220,
                    position_type="核心仓",
                    thesis="动力电池龙头",
                )
                with patch("src.growth_portfolio.LLMClient") as client_cls, patch(
                    "src.market_data.provider_router.fetch_quote"
                ) as fetch_quote:
                    fetch_quote.return_value.to_dict.return_value = {
                        "status": "ok",
                        "source": "yfinance",
                        "market": "CN",
                        "symbol": "300750.SZ",
                        "data": {"current_price": 221},
                        "error": "",
                    }
                    client_cls.for_framework.return_value.complete.return_value = "复盘结果"
                    reply = growth_portfolio.review_growth_symbol("300750.SZ", chat_id="cli")

        self.assertEqual(reply, "复盘结果")
        kwargs = client_cls.for_framework.return_value.complete.call_args.kwargs
        self.assertEqual(kwargs["framework_id"], "Growth_Engine")
        self.assertEqual(kwargs["context_bundle_id"], "CN_Alpha_Growth")
        self.assertIn("300750.SZ", kwargs["user_prompt"])
        self.assertIn("market_data", kwargs["user_prompt"])

    def test_enrich_growth_snapshot_uses_market_data_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _growth_paths(Path(tmp))
            with _patch_growth_paths(paths):
                growth_portfolio.upsert_growth_holding(
                    symbol="QQQI.US",
                    name="QQQI",
                    market="US",
                    shares=10,
                    cost_price=50,
                    current_price=56,
                    position_type="观察仓",
                    thesis="美元现金流",
                )
                snapshot = growth_portfolio.build_growth_snapshot(market="US")
                with patch("src.market_data.provider_router.fetch_quote") as fetch_quote:
                    fetch_quote.return_value.to_dict.return_value = {
                        "status": "ok",
                        "source": "longbridge",
                        "market": "US",
                        "symbol": "QQQI.US",
                        "data": {"current_price": 57.2},
                        "error": "",
                    }
                    enriched = growth_portfolio.enrich_growth_snapshot_with_market_data(snapshot)

        self.assertEqual(enriched["market_data"]["QQQI.US"]["source"], "longbridge")
        fetch_quote.assert_called_once_with("QQQI.US", market="US")

    def test_daily_review_empty_market_returns_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _growth_paths(Path(tmp))
            with _patch_growth_paths(paths):
                reply = growth_portfolio.review_growth_daily("US", chat_id="cli")

        self.assertIn("本地持仓和自选列表均为空", reply)

    def test_upsert_growth_watch_item(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _growth_paths(Path(tmp))
            with _patch_growth_paths(paths):
                result = growth_portfolio.upsert_growth_watch_item(
                    symbol="MSFT.US",
                    name="Microsoft",
                    market="US",
                    priority="high",
                    watch_reason="AI 平台",
                    trigger_condition="回撤到关键均线",
                )
                snapshot = growth_portfolio.build_growth_snapshot(market="US")

        self.assertEqual(result["watch_action"], "created")
        self.assertEqual(snapshot["summary"]["watchlist_count"], 1)
        self.assertEqual(snapshot["watchlist"][0]["sub_framework"], "US_Disruptive_Growth")


def _growth_paths(root: Path) -> dict[str, Path]:
    framework = root / "Growth_Engine"
    data = framework / "data"
    templates = framework / "data_templates"
    sub_frameworks = framework / "sub_frameworks"
    templates.mkdir(parents=True)
    sub_frameworks.mkdir(parents=True)
    (framework / "constitution.md").write_text("Growth constitution", encoding="utf-8")
    (sub_frameworks / "CN_Alpha_Growth.md").write_text("CN constitution", encoding="utf-8")
    (sub_frameworks / "US_Disruptive_Growth.md").write_text("US constitution", encoding="utf-8")
    (templates / "growth_holdings.csv").write_text(
        "symbol,name,market,sub_framework,shares,cost_price,current_price,position_type,thesis,status,last_review_at,notes\n",
        encoding="utf-8",
    )
    (templates / "growth_watchlist.csv").write_text(
        "symbol,name,market,sub_framework,priority,watch_reason,trigger_condition,status,last_review_at,notes\n",
        encoding="utf-8",
    )
    return {
        "framework": framework,
        "data": data,
        "templates": templates,
        "holdings": data / "growth_holdings.csv",
        "watchlist": data / "growth_watchlist.csv",
    }


def _patch_growth_paths(paths: dict[str, Path]):
    return patch.multiple(
        growth_portfolio,
        GROWTH_DIR=paths["framework"],
        DATA_DIR=paths["data"],
        TEMPLATE_DIR=paths["templates"],
        HOLDINGS_PATH=paths["holdings"],
        WATCHLIST_PATH=paths["watchlist"],
    )


if __name__ == "__main__":
    unittest.main()
