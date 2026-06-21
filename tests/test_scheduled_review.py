from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

from src import scheduled_review


class ScheduledReviewTest(unittest.TestCase):
    def test_save_and_read_recent_daily_reviews(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(scheduled_review, "FRAMEWORKS_DIR", Path(tmp) / "frameworks"):
                context = _context()
                old_record, _ = scheduled_review.save_scheduled_review(
                    framework_id="Growth_Engine",
                    market="US",
                    workflow_type="close",
                    review_date=date(2026, 6, 3),
                    trace_id="trace_old",
                    context_bundle_id="US_Disruptive_Growth",
                    context=context,
                    result="旧复盘",
                    status="ok",
                    chat_id="cli",
                )
                new_record, _ = scheduled_review.save_scheduled_review(
                    framework_id="Growth_Engine",
                    market="US",
                    workflow_type="close",
                    review_date=date(2026, 6, 4),
                    trace_id="trace_new",
                    context_bundle_id="US_Disruptive_Growth",
                    context=context,
                    result="新复盘",
                    status="ok",
                    chat_id="cli",
                )

                records = scheduled_review.read_recent_daily_reviews(
                    "Growth_Engine",
                    market="US",
                    workflow_type="close",
                    before=date(2026, 6, 5),
                    limit=2,
                )

        self.assertEqual([record["record_id"] for record in records], [new_record["record_id"], old_record["record_id"]])

    def test_build_daily_context_includes_previous_close_and_weekly_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "frameworks"
            _write_strategy_files(root)
            with patch.object(scheduled_review, "FRAMEWORKS_DIR", root), patch(
                "src.growth_portfolio.build_growth_snapshot"
            ) as build_snapshot, patch("src.growth_universe.sync_growth_universe") as sync_universe, patch(
                "src.market_data.provider_router.fetch_quote"
            ) as fetch_quote, patch(
                "src.market_intel.fetch_company_news"
            ) as fetch_news, patch("src.market_intel.fetch_company_announcements") as fetch_announcements, patch(
                "src.research_dossier.build_research_dossier_snapshot"
            ) as dossier_snapshot, patch(
                "src.longbridge_account_provider.build_account_activity_snapshot"
            ) as account_snapshot, patch(
                "src.longbridge_quote_provider.build_market_context_snapshot"
            ) as market_context, patch(
                "src.longbridge_fundamental_provider.build_fundamental_context_snapshot"
            ) as fundamental_context:
                account_snapshot.return_value = _account_activity()
                market_context.return_value = _market_context()
                fundamental_context.return_value = _fundamental_context()
                build_snapshot.return_value = {
                    "as_of": "2026-06-04",
                    "market_filter": "US",
                    "missing_files": [],
                    "summary": {"holding_count": 0, "watchlist_count": 0},
                    "holdings": [],
                    "watchlist": [],
                }
                sync_universe.return_value = {
                    "classification_rule": "longbridge universe",
                    "write_policy": "read_only_context",
                    "universe": [
                        {
                            "symbol": "NVDA.US",
                            "name": "NVIDIA",
                            "market": "US",
                            "has_position": True,
                            "reason": "长桥美股正股",
                        }
                    ],
                    "summary": {"universe_count": 1, "excluded_count": 0},
                }
                fetch_quote.return_value.to_dict.return_value = {
                    "status": "ok",
                    "source": "mock",
                    "market": "US",
                    "symbol": "NVDA.US",
                    "data": {"current_price": 100},
                    "error": "",
                }
                fetch_news.return_value = _intel("news", "新闻")
                fetch_announcements.return_value = _intel("announcement", "公告")
                dossier_snapshot.return_value = {
                    "exists": True,
                    "path": "dossier.json",
                    "freshness": {"stale": False},
                    "dossier": {"core_thesis": "长期逻辑", "risk_points": ["风险"]},
                }

                scheduled_review.save_scheduled_review(
                    framework_id="Growth_Engine",
                    market="US",
                    workflow_type="close",
                    review_date=date(2026, 6, 3),
                    trace_id="trace_old",
                    context_bundle_id="US_Disruptive_Growth",
                    context=_context(),
                    result="上一交易日复盘",
                    status="ok",
                    chat_id="cli",
                )
                scheduled_review.save_scheduled_review(
                    framework_id="Growth_Engine",
                    market="ALL",
                    workflow_type="weekly",
                    review_date=date(2026, 5, 31),
                    trace_id="trace_weekly",
                    context_bundle_id="Growth_Engine",
                    context=_context(),
                    result="最近周计划",
                    status="ok",
                    chat_id="cli",
                )

                context = scheduled_review.build_daily_review_context(
                    framework_id="Growth_Engine",
                    market="US",
                    workflow_type="premarket",
                    as_of=date(2026, 6, 4),
                )

        self.assertEqual(context["tracked_symbols"][0]["symbol"], "NVDA.US")
        self.assertIn("上一交易日复盘", context["history"]["previous_close"][0]["result"])
        self.assertIn("最近周计划", context["history"]["latest_weekly_plan"][0]["result"])
        self.assertIn("market_data", context)
        self.assertIn("symbol_intel", context)
        self.assertIn("research_dossiers", context)
        self.assertEqual(context["account_activity"]["summary"]["execution_count"], 1)
        self.assertEqual(context["longbridge_market_context"]["summary"]["quote_count"], 1)
        self.assertEqual(context["longbridge_fundamental_context"]["summary"]["valuation_count"], 1)
        self.assertEqual(context["market_data"]["NVDA.US"]["data"]["MA120"], 100)
        self.assertEqual(context["research_engine"]["engine"], "growth_research_mvp")
        self.assertEqual(context["research_engine"]["market_context_summary"]["symbols_with_ma120"], 1)
        self.assertEqual(context["research_engine"]["fundamental_context_summary"]["symbols_with_valuation"], 1)
        self.assertEqual(context["research_engine"]["research_signals"][0]["ticker"], "NVDA.US")
        self.assertEqual(context["operation_framework"]["engine"], "operation_framework")
        self.assertEqual(context["operation_framework"]["operation_plans"][0]["ticker"], "NVDA.US")

    def test_weekly_context_reads_past_week_daily_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "frameworks"
            _write_strategy_files(root)
            with patch.object(scheduled_review, "FRAMEWORKS_DIR", root), patch(
                "src.growth_portfolio.build_growth_snapshot"
            ) as build_snapshot, patch("src.growth_universe.sync_growth_universe") as sync_universe, patch(
                "src.market_intel.fetch_company_news"
            ) as fetch_news, patch(
                "src.market_intel.fetch_company_announcements"
            ) as fetch_announcements, patch("src.research_dossier.build_research_dossier_snapshot") as dossier_snapshot, patch(
                "src.longbridge_account_provider.build_account_activity_snapshot"
            ) as account_snapshot, patch(
                "src.longbridge_quote_provider.build_market_context_snapshot"
            ) as market_context, patch(
                "src.longbridge_fundamental_provider.build_fundamental_context_snapshot"
            ) as fundamental_context:
                account_snapshot.return_value = _account_activity()
                market_context.return_value = _market_context()
                fundamental_context.return_value = _fundamental_context()
                build_snapshot.return_value = {
                    "as_of": "2026-06-07",
                    "market_filter": "US",
                    "missing_files": [],
                    "summary": {"holding_count": 0, "watchlist_count": 0},
                    "holdings": [],
                    "watchlist": [],
                }
                sync_universe.return_value = {
                    "classification_rule": "longbridge universe",
                    "write_policy": "read_only_context",
                    "universe": [
                        {
                            "symbol": "NVDA.US",
                            "name": "NVIDIA",
                            "market": "US",
                            "has_position": False,
                            "reason": "AI",
                        }
                    ],
                    "summary": {"universe_count": 1, "excluded_count": 0},
                }
                fetch_news.return_value = _intel("news", "新闻")
                fetch_announcements.return_value = _intel("announcement", "公告")
                dossier_snapshot.return_value = {
                    "exists": False,
                    "path": "dossier.json",
                    "freshness": {"stale": False},
                    "dossier": {},
                }

                scheduled_review.save_scheduled_review(
                    framework_id="Growth_Engine",
                    market="US",
                    workflow_type="close",
                    review_date=date(2026, 6, 5),
                    trace_id="trace_daily",
                    context=_context(),
                    context_bundle_id="US_Disruptive_Growth",
                    result="本周日报",
                    status="ok",
                    chat_id="cli",
                )
                context = scheduled_review.build_weekly_review_context(
                    framework_id="Growth_Engine",
                    as_of=date(2026, 6, 7),
                )

        self.assertEqual(context["record_counts"]["total"], 1)
        self.assertIn("本周日报", context["daily_records"][0]["result"])
        self.assertEqual(context["tracked_symbols"][0]["symbol"], "NVDA.US")
        self.assertIn("US", context["account_activity_by_market"])
        self.assertEqual(context["longbridge_market_context"]["summary"]["quote_count"], 1)
        self.assertEqual(context["longbridge_fundamental_context"]["summary"]["valuation_count"], 1)
        self.assertEqual(context["research_engine"]["engine"], "growth_research_mvp")
        self.assertEqual(context["operation_framework"]["engine"], "operation_framework")

    def test_growth_us_context_uses_longbridge_non_cash_positions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "frameworks"
            _write_strategy_files(root)
            with patch.object(scheduled_review, "FRAMEWORKS_DIR", root), patch(
                "src.growth_portfolio.build_growth_snapshot"
            ) as build_snapshot, patch("src.growth_universe.sync_growth_universe") as sync_universe, patch(
                "src.market_data.provider_router.fetch_quote"
            ) as fetch_quote, patch("src.market_intel.fetch_company_news") as fetch_news, patch(
                "src.market_intel.fetch_company_announcements"
            ) as fetch_announcements, patch("src.research_dossier.build_research_dossier_snapshot") as dossier_snapshot, patch(
                "src.longbridge_account_provider.build_account_activity_snapshot"
            ) as account_snapshot, patch(
                "src.longbridge_quote_provider.build_market_context_snapshot"
            ) as market_context, patch(
                "src.longbridge_fundamental_provider.build_fundamental_context_snapshot"
            ) as fundamental_context:
                account_snapshot.return_value = _account_activity()
                market_context.return_value = _market_context()
                fundamental_context.return_value = _fundamental_context()
                build_snapshot.return_value = {
                    "as_of": "2026-06-04",
                    "market_filter": "US",
                    "missing_files": [],
                    "summary": {"holding_count": 0, "watchlist_count": 0},
                    "holdings": [],
                    "watchlist": [],
                }
                sync_universe.return_value = {
                    "classification_rule": "长桥 universe",
                    "write_policy": "read_only_context",
                    "universe": [
                        {
                            "symbol": "NVDA.US",
                            "name": "NVIDIA",
                            "market": "US",
                            "has_position": True,
                            "quantity": 2,
                            "cost_price": 900,
                            "current_price": 950,
                            "reason": "长桥美股持仓且不属于 Cash Anchor 固定现金流标的。",
                        },
                        {
                            "symbol": "AVGO.US",
                            "name": "Broadcom",
                            "market": "US",
                            "has_position": False,
                            "group_name": "us",
                            "is_pinned": False,
                            "reason": "长桥美股自选且不属于 Cash Anchor 固定现金流标的。",
                        }
                    ],
                    "summary": {"universe_count": 2, "excluded_count": 0},
                }
                fetch_quote.return_value.to_dict.return_value = {
                    "status": "ok",
                    "source": "mock",
                    "market": "US",
                    "symbol": "NVDA.US",
                    "data": {},
                    "error": "",
                }
                fetch_news.return_value = _intel("news", "新闻")
                fetch_announcements.return_value = _intel("announcement", "公告")
                dossier_snapshot.return_value = {
                    "exists": False,
                    "path": "dossier.json",
                    "freshness": {"stale": False},
                    "dossier": {},
                }

                context = scheduled_review.build_daily_review_context(
                    framework_id="Growth_Engine",
                    market="US",
                    workflow_type="premarket",
                    as_of=date(2026, 6, 4),
                )

        self.assertEqual(context["tracked_symbols"][0]["symbol"], "NVDA.US")
        self.assertEqual(context["tracked_symbols"][0]["source"], "longbridge_growth_universe")
        self.assertEqual(context["tracked_symbols"][1]["symbol"], "AVGO.US")
        self.assertEqual(context["tracked_symbols"][1]["source"], "longbridge_growth_universe")
        self.assertEqual(context["snapshot"]["summary"]["longbridge_growth_universe_count"], 2)
        self.assertEqual(context["snapshot"]["summary"]["longbridge_recent_execution_count"], 1)
        self.assertIn("longbridge_market_snapshot", context["market_data"]["NVDA.US"]["data"])

    def test_missing_research_dossier_is_optional_note_not_data_gap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "frameworks"
            _write_strategy_files(root)
            with patch.object(scheduled_review, "FRAMEWORKS_DIR", root), patch(
                "src.growth_portfolio.build_growth_snapshot"
            ) as build_snapshot, patch("src.growth_universe.sync_growth_universe") as sync_universe, patch(
                "src.market_data.provider_router.fetch_quote"
            ) as fetch_quote, patch(
                "src.market_intel.fetch_company_news"
            ) as fetch_news, patch("src.market_intel.fetch_company_announcements") as fetch_announcements, patch(
                "src.research_dossier.build_research_dossier_snapshot"
            ) as dossier_snapshot, patch(
                "src.longbridge_account_provider.build_account_activity_snapshot"
            ) as account_snapshot, patch(
                "src.longbridge_quote_provider.build_market_context_snapshot"
            ) as market_context, patch(
                "src.longbridge_fundamental_provider.build_fundamental_context_snapshot"
            ) as fundamental_context:
                account_snapshot.return_value = _account_activity()
                market_context.return_value = _market_context()
                fundamental_context.return_value = _fundamental_context()
                build_snapshot.return_value = {
                    "as_of": "2026-06-04",
                    "market_filter": "US",
                    "missing_files": [],
                    "summary": {"holding_count": 0, "watchlist_count": 0},
                    "holdings": [],
                    "watchlist": [],
                }
                sync_universe.return_value = {
                    "classification_rule": "longbridge universe",
                    "write_policy": "read_only_context",
                    "universe": [
                        {
                            "symbol": "NVDA.US",
                            "name": "NVIDIA",
                            "market": "US",
                            "has_position": False,
                            "reason": "AI",
                        }
                    ],
                    "summary": {"universe_count": 1, "excluded_count": 0},
                }
                fetch_quote.return_value.to_dict.return_value = {
                    "status": "ok",
                    "source": "mock",
                    "market": "US",
                    "symbol": "NVDA.US",
                    "data": {},
                    "error": "",
                }
                fetch_news.return_value = _intel("news", "新闻")
                fetch_announcements.return_value = _intel("announcement", "公告")
                dossier_snapshot.return_value = {
                    "exists": False,
                    "path": "dossier.json",
                    "freshness": {"stale": False},
                    "dossier": {},
                }

                context = scheduled_review.build_daily_review_context(
                    framework_id="Growth_Engine",
                    market="US",
                    workflow_type="premarket",
                    as_of=date(2026, 6, 4),
                )

        self.assertFalse(any("未建立研究档案" in item for item in context["data_gaps"]))
        self.assertTrue(any("未建立研究档案" in item for item in context["optional_data_notes"]))

    def test_longbridge_account_failure_is_data_gap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "frameworks"
            _write_strategy_files(root)
            with patch.object(scheduled_review, "FRAMEWORKS_DIR", root), patch(
                "src.growth_portfolio.build_growth_snapshot"
            ) as build_snapshot, patch("src.growth_universe.sync_growth_universe") as sync_universe, patch(
                "src.market_data.provider_router.fetch_quote"
            ) as fetch_quote, patch("src.market_intel.fetch_company_news") as fetch_news, patch(
                "src.market_intel.fetch_company_announcements"
            ) as fetch_announcements, patch("src.research_dossier.build_research_dossier_snapshot") as dossier_snapshot, patch(
                "src.longbridge_account_provider.build_account_activity_snapshot"
            ) as account_snapshot, patch(
                "src.longbridge_quote_provider.build_market_context_snapshot"
            ) as market_context, patch(
                "src.longbridge_fundamental_provider.build_fundamental_context_snapshot"
            ) as fundamental_context:
                market_context.return_value = _market_context()
                fundamental_context.return_value = _fundamental_context()
                build_snapshot.return_value = {
                    "as_of": "2026-06-04",
                    "market_filter": "US",
                    "missing_files": [],
                    "summary": {"holding_count": 0, "watchlist_count": 0},
                    "holdings": [],
                    "watchlist": [],
                }
                sync_universe.return_value = {
                    "classification_rule": "longbridge universe",
                    "write_policy": "read_only_context",
                    "universe": [
                        {
                            "symbol": "NVDA.US",
                            "name": "NVIDIA",
                            "market": "US",
                            "has_position": True,
                            "reason": "AI",
                        }
                    ],
                    "summary": {"universe_count": 1, "excluded_count": 0},
                }
                account_snapshot.side_effect = RuntimeError("account query failed")
                fetch_quote.return_value.to_dict.return_value = {
                    "status": "ok",
                    "source": "mock",
                    "market": "US",
                    "symbol": "NVDA.US",
                    "data": {},
                    "error": "",
                }
                fetch_news.return_value = _intel("news", "新闻")
                fetch_announcements.return_value = _intel("announcement", "公告")
                dossier_snapshot.return_value = {
                    "exists": False,
                    "path": "dossier.json",
                    "freshness": {"stale": False},
                    "dossier": {},
                }

                context = scheduled_review.build_daily_review_context(
                    framework_id="Growth_Engine",
                    market="US",
                    workflow_type="premarket",
                    as_of=date(2026, 6, 4),
                )

        self.assertEqual(context["account_activity"], {})
        self.assertTrue(any("长桥账户/成交只读快照读取失败" in item for item in context["data_gaps"]))

    def test_run_scheduled_close_review_persists_llm_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "frameworks"
            _write_strategy_files(root)
            fake_client = Mock()
            fake_client.complete.return_value = "收盘复盘结果"
            with patch.object(scheduled_review, "FRAMEWORKS_DIR", root), patch(
                "src.growth_portfolio.build_growth_snapshot"
            ) as build_snapshot, patch("src.growth_universe.sync_growth_universe") as sync_universe, patch(
                "src.market_data.provider_router.fetch_quote"
            ) as fetch_quote, patch(
                "src.market_intel.fetch_company_news"
            ) as fetch_news, patch("src.market_intel.fetch_company_announcements") as fetch_announcements, patch(
                "src.research_dossier.build_research_dossier_snapshot"
            ) as dossier_snapshot, patch("src.longbridge_account_provider.build_account_activity_snapshot") as account_snapshot, patch(
                "src.longbridge_quote_provider.build_market_context_snapshot"
            ) as market_context, patch(
                "src.longbridge_fundamental_provider.build_fundamental_context_snapshot"
            ) as fundamental_context, patch(
                "src.scheduled_review.LLMClient"
            ) as client_cls:
                account_snapshot.return_value = _account_activity()
                market_context.return_value = _market_context()
                fundamental_context.return_value = _fundamental_context()
                build_snapshot.return_value = {
                    "as_of": "2026-06-04",
                    "market_filter": "US",
                    "missing_files": [],
                    "summary": {"holding_count": 0, "watchlist_count": 0},
                    "holdings": [],
                    "watchlist": [],
                }
                sync_universe.return_value = {
                    "classification_rule": "longbridge universe",
                    "write_policy": "read_only_context",
                    "universe": [
                        {
                            "symbol": "NVDA.US",
                            "name": "NVIDIA",
                            "market": "US",
                            "has_position": True,
                            "reason": "AI",
                        }
                    ],
                    "summary": {"universe_count": 1, "excluded_count": 0},
                }
                fetch_quote.return_value.to_dict.return_value = {
                    "status": "ok",
                    "source": "mock",
                    "market": "US",
                    "symbol": "NVDA.US",
                    "data": {},
                    "error": "",
                }
                fetch_news.return_value = _intel("news", "新闻")
                fetch_announcements.return_value = _intel("announcement", "公告")
                dossier_snapshot.return_value = {
                    "exists": True,
                    "path": "dossier.json",
                    "freshness": {"stale": False},
                    "dossier": {},
                }
                client_cls.for_framework.return_value = fake_client

                reply = scheduled_review.run_scheduled_close_review(
                    "Growth_Engine",
                    "US",
                    chat_id="cli",
                    as_of=date(2026, 6, 4),
                )

        self.assertIn("收盘复盘结果", reply)
        self.assertIn("记录：", reply)
        client_cls.for_framework.assert_called_once_with("Growth_Engine")
        self.assertIn("same_day_premarket", fake_client.complete.call_args.kwargs["user_prompt"])


def _context() -> dict:
    return {
        "tracked_symbols": [{"symbol": "NVDA.US", "market": "US"}],
        "data_gaps": [],
        "snapshot": {"data_files": {}},
    }


def _account_activity(status: str = "ok") -> dict:
    return {
        "source": "longbridge_cli",
        "scope": "account_activity_snapshot",
        "as_of": "2026-06-04T08:00:00",
        "status": status,
        "period": {"start": "2026-05-28", "end": "2026-06-04", "days": 7},
        "currency": "USD",
        "summary": {
            "cash_info_count": 1,
            "holding_count": 2,
            "order_count": 1,
            "execution_count": 1,
        },
        "sections": {
            "order_history": {
                "summary": {"order_count": 1},
                "data": [{"order_id": "o1", "symbol": "NVDA.US"}],
            },
            "execution_history": {
                "summary": {"execution_count": 1},
                "data": [{"trade_id": "t1", "symbol": "NVDA.US"}],
            },
        },
        "data_quality": {"source_chain": [], "limitations": []},
        "write_policy": "read_only_account_data; no order placement, amendment, or cancellation",
    }


def _market_context(status: str = "ok") -> dict:
    return {
        "source": "longbridge_cli",
        "scope": "market_context_snapshot",
        "as_of": "2026-06-04T08:00:00",
        "market": "US",
        "symbols": ["NVDA.US"],
        "kline_symbols": ["NVDA.US"],
        "summary": {
            "symbol_count": 1,
            "quote_count": 1,
            "kline_symbol_count": 1,
            "market_status_count": 1,
            "trading_day_count": 5,
        },
        "symbol_data": {
            "NVDA.US": {
                "quote": {
                    "symbol": "NVDA.US",
                    "current_price": 120,
                    "quote_source": "last",
                    "timestamp": "",
                },
                "technical": {
                    "latest_close": 120,
                    "ma20": 110,
                    "ma50": 105,
                    "ma120": 100,
                    "ma120_relation": "above_ma120",
                    "kline_count": 140,
                },
                "kline_preview": [{"time": "2026-06-04", "close": 120}],
            }
        },
        "data_quality": {"status": status, "limitations": []},
        "write_policy": "read_only_market_data; no order placement, amendment, or cancellation",
    }


def _fundamental_context(status: str = "ok") -> dict:
    return {
        "source": "longbridge_cli",
        "scope": "fundamental_context_snapshot",
        "as_of": "2026-06-04T08:00:00",
        "market": "US",
        "symbols": ["NVDA.US"],
        "summary": {
            "symbol_count": 1,
            "company_profile_count": 1,
            "valuation_count": 1,
            "financial_report_snapshot_count": 1,
            "forecast_eps_count": 1,
            "consensus_count": 1,
            "dividend_history_count": 1,
        },
        "symbol_data": {
            "NVDA.US": {
                "company_name": "NVIDIA",
                "industry": "Semiconductors",
                "valuation_desc": "current P/E in reasonable range",
                "valuation_metrics": {"metrics": {"pe": {"desc": "current P/E in reasonable range"}}},
                "financial_report_snapshot": {"summary": "AI data center growth beats expectations"},
                "forecast_eps": {"items": [{"forecast_eps_mean": "3.04"}]},
                "consensus": {"list": [{"details": [{"key": "revenue", "estimate": "100"}]}]},
                "dividend_count": 1,
                "dividend_preview": [{"desc": "Dividend: USD 0.01/share"}],
            }
        },
        "data_quality": {"status": status, "limitations": []},
        "write_policy": "read_only_fundamental_data; no order placement, amendment, or cancellation",
    }


def _intel(data_type: str, title: str) -> dict:
    return {
        "status": "ok",
        "source": "mock",
        "data_type": data_type,
        "data": {
            "items": [
                {
                    "title": title,
                    "summary": "摘要",
                    "published_at": "2026-06-04",
                    "source": "mock",
                    "url": "",
                }
            ]
        },
        "error": "",
    }


def _write_strategy_files(root: Path) -> None:
    for framework_id, sub_files in {
        "Growth_Engine": ["US_Disruptive_Growth"],
        "Cash_Anchor": ["CN_Dividend_Income", "US_Income_Options"],
    }.items():
        framework_dir = root / framework_id
        sub_dir = framework_dir / "sub_frameworks"
        sub_dir.mkdir(parents=True)
        (framework_dir / "constitution.md").write_text(f"{framework_id} constitution", encoding="utf-8")
        for name in sub_files:
            (sub_dir / f"{name}.md").write_text(f"{name} constitution", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
