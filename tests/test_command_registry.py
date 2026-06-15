from __future__ import annotations

import unittest
from unittest.mock import patch

from src.command_registry import handle_command, help_text, resolve_command


class CommandRegistryTest(unittest.TestCase):
    def test_resolve_command_aliases(self) -> None:
        resolved = resolve_command("/salary 5000")
        self.assertIsNotNone(resolved)
        command, args = resolved
        self.assertEqual(command.name, "contribute")
        self.assertEqual(args, "5000")

        resolved = resolve_command("/target contribution=50000")
        self.assertIsNotNone(resolved)
        command, args = resolved
        self.assertEqual(command.name, "plan")
        self.assertEqual(args, "contribution=50000")

    def test_help_lists_ledger_commands(self) -> None:
        text = help_text()
        self.assertIn("/contribute", text)
        self.assertIn("/plan", text)
        self.assertIn("/plan contribution=<amount>", text)
        self.assertNotIn("/plan contribution=<amount> dividend=<amount>", text)
        self.assertIn("/holding", text)
        self.assertIn("/holdings", text)
        self.assertIn("/cash-watchlist", text)
        self.assertIn("/sync longbridge dividends", text)
        self.assertIn("/growth-universe", text)
        self.assertIn("/growth-review", text)
        self.assertIn("/absorb", text)
        self.assertIn("/dossier-refresh", text)
        self.assertIn("/review-dossier", text)
        self.assertIn("/scheduled-review", text)
        self.assertIn("Cash_Anchor/CN_Dividend_Income", text)
        self.assertIn("Cash_Anchor/US_Income_Options", text)
        self.assertIn("Growth_Engine/US_Disruptive_Growth", text)

    def test_plan_usage_message(self) -> None:
        reply = handle_command("/plan", "cli")
        self.assertIsNotNone(reply)
        self.assertIn("用法：/plan", reply or "")
        self.assertIn("不再设置目标年分红", reply or "")

    def test_plan_rejects_dividend_target(self) -> None:
        reply = handle_command("/plan dividend=120000", "cli")
        self.assertIsNotNone(reply)
        self.assertIn("已取消目标年分红", reply or "")

    def test_contribute_rejects_bad_amount(self) -> None:
        reply = handle_command("/contribute abc", "cli")
        self.assertEqual(reply, "投入金额无法解析：abc")

    def test_holding_usage_message(self) -> None:
        reply = handle_command("/holding symbol=600000", "cli")
        self.assertIsNotNone(reply)
        self.assertIn("用法：/holding", reply or "")

    @patch("src.portfolio_ledger.upsert_holding")
    def test_holding_allows_missing_dividend(self, upsert_holding) -> None:
        upsert_holding.return_value = {
            "updated_holding": {
                "symbol": "600900.SH",
                "name": "长江电力",
                "currency": "CNY",
                "shares": 1000,
                "cost_price": 24.5,
                "current_price": 24.5,
                "annual_dividend_per_share": 0,
                "tax_rate": 0,
                "notes": "current_price=pending_quote",
            },
            "holding_action": "created",
            "summary": {
                "net_annual_dividend": 0,
            },
            "holdings_path": "holdings.csv",
        }

        reply = handle_command(
            "/holding symbol=600900.SH name=长江电力 shares=1000 cost=24.5",
            "cli",
        )

        self.assertIsNotNone(reply)
        self.assertIn("待估算", reply or "")
        self.assertIn("当前价：待查询", reply or "")
        upsert_holding.assert_called_once()
        self.assertEqual(upsert_holding.call_args.kwargs["annual_dividend_per_share"], 0.0)
        self.assertEqual(upsert_holding.call_args.kwargs["tax_rate"], 0.0)
        self.assertEqual(upsert_holding.call_args.kwargs["current_price"], 24.5)

    @patch("src.portfolio_ledger.upsert_holding")
    def test_holding_supports_short_positional_args(self, upsert_holding) -> None:
        upsert_holding.return_value = {
            "updated_holding": {
                "symbol": "600900.SH",
                "name": "600900.SH",
                "currency": "CNY",
                "shares": 1000,
                "cost_price": 24.5,
                "current_price": 24.5,
                "annual_dividend_per_share": 0,
                "tax_rate": 0,
                "notes": "current_price=pending_quote",
            },
            "holding_action": "created",
            "summary": {
                "net_annual_dividend": 0,
            },
            "holdings_path": "holdings.csv",
        }

        reply = handle_command("/holding 600900.SH 1000 24.5", "cli")

        self.assertIsNotNone(reply)
        self.assertIn("600900.SH", reply or "")
        kwargs = upsert_holding.call_args.kwargs
        self.assertEqual(kwargs["symbol"], "600900.SH")
        self.assertEqual(kwargs["shares"], 1000)
        self.assertEqual(kwargs["cost_price"], 24.5)
        self.assertEqual(kwargs["current_price"], 24.5)
        self.assertIn("current_price=pending_quote", kwargs["notes"])

    @patch("src.portfolio_ledger.upsert_holding")
    def test_holdings_batch_supports_short_positional_rows(self, upsert_holding) -> None:
        upsert_holding.side_effect = [
            {
                "updated_holding": {"symbol": "600900.SH", "name": "长江电力"},
                "holding_action": "created",
            },
            {
                "updated_holding": {"symbol": "601088.SH", "name": "中国神华"},
                "holding_action": "updated",
            },
        ]

        reply = handle_command(
            "/holdings\n"
            "600900.SH 长江电力 1000 24.5\n"
            "601088.SH 中国神华 500 31.2",
            "cli",
        )

        self.assertIsNotNone(reply)
        self.assertIn("成功 2 条", reply or "")
        self.assertIn("600900.SH", reply or "")
        self.assertEqual(upsert_holding.call_count, 2)
        first_kwargs = upsert_holding.call_args_list[0].kwargs
        self.assertEqual(first_kwargs["name"], "长江电力")
        self.assertEqual(first_kwargs["shares"], 1000)
        self.assertEqual(first_kwargs["cost_price"], 24.5)

    @patch("src.portfolio_ledger.upsert_holding")
    def test_holdings_batch_ignores_feishu_mention_tokens(self, upsert_holding) -> None:
        upsert_holding.return_value = {
            "updated_holding": {"symbol": "600795", "name": "国电电力"},
            "holding_action": "created",
        }

        reply = handle_command("/holdings\n600795 国电电力 1000 5.2 @_user_1", "cli")

        self.assertIsNotNone(reply)
        self.assertIn("成功 1 条", reply or "")
        kwargs = upsert_holding.call_args.kwargs
        self.assertEqual(kwargs["symbol"], "600795")
        self.assertEqual(kwargs["name"], "国电电力")
        self.assertEqual(kwargs["shares"], 1000)
        self.assertEqual(kwargs["cost_price"], 5.2)

    def test_transaction_command_usage_messages(self) -> None:
        self.assertIn("用法：/buy", handle_command("/buy symbol=600000", "cli") or "")
        self.assertIn("用法：/sell", handle_command("/sell symbol=600000", "cli") or "")
        self.assertIn("用法：/dividend", handle_command("/dividend symbol=600000", "cli") or "")

    def test_single_growth_write_commands_are_not_registered(self) -> None:
        self.assertIsNone(resolve_command("/growth-holding symbol=NVDA.US"))
        self.assertIsNone(resolve_command("/growth-watch symbol=NVDA.US"))

    @patch("src.longbridge_provider.sync_longbridge_positions")
    def test_sync_longbridge_uses_provider(self, sync_positions) -> None:
        sync_positions.return_value = {
            "summary": {"total_positions": 1, "cash_anchor_positions": 1, "excluded_positions": 0},
            "included": [
                {
                    "symbol": "QQQI.US",
                    "name": "QQQI",
                    "quantity": 10,
                    "cost_price": 50,
                    "currency": "USD",
                }
            ],
            "excluded": [],
        }
        reply = handle_command("/sync longbridge", "cli")
        self.assertIsNotNone(reply)
        self.assertIn("长桥持仓同步提案", reply or "")
        self.assertIn("QQQI.US", reply or "")

    @patch("src.longbridge_provider.sync_longbridge_us_income_distributions")
    def test_sync_longbridge_dividends_uses_provider(self, sync_income) -> None:
        sync_income.return_value = {
            "period": {"start": "2026-01-01", "end": "2026-06-04"},
            "symbols": ["QQQI.US"],
            "cash_flow_import": {"created_count": 1, "duplicate_count": 0},
            "history_import": {"created_count": 1, "updated_count": 0, "total_count": 1, "failures": []},
            "forecast": {
                "positions": [
                    {
                        "symbol": "QQQI.US",
                        "currency": "USD",
                        "trailing_3m": {"estimated_annual_cash": 1200},
                        "trailing_6m": {"estimated_annual_cash": 1100},
                        "trailing_12m": {"estimated_annual_cash": 1000},
                    }
                ]
            },
        }

        reply = handle_command("/sync longbridge dividends start=2026-01-01 end=2026-06-04", "cli")

        self.assertIsNotNone(reply)
        self.assertIn("长桥美元分配同步完成", reply or "")
        self.assertIn("QQQI.US", reply or "")
        self.assertEqual(sync_income.call_args.kwargs["start"].isoformat(), "2026-01-01")
        self.assertEqual(sync_income.call_args.kwargs["end"].isoformat(), "2026-06-04")

    @patch("src.growth_universe.sync_growth_universe")
    def test_sync_longbridge_growth_uses_provider(self, sync_growth) -> None:
        sync_growth.return_value = {
            "classification_rule": "非现金流美股归 Growth",
            "universe": [
                {
                    "symbol": "NVDA.US",
                    "name": "NVIDIA",
                    "asset_type": "stock",
                    "source_types": ["longbridge_position"],
                    "source_groups": [],
                    "has_position": True,
                }
            ],
            "summary": {
                "universe_count": 1,
                "source_positions": 1,
                "source_watch_items": 0,
                "option_contracts_mapped": 0,
                "excluded_cash_anchor": 0,
                "excluded_leveraged_etf": 0,
                "excluded_index": 0,
                "excluded_non_us": 0,
            },
            "excluded": [],
        }

        reply = handle_command("/sync longbridge growth", "cli")

        self.assertIsNotNone(reply)
        self.assertIn("Growth Engine 长桥 universe", reply or "")
        self.assertIn("NVDA.US", reply or "")
        sync_growth.assert_called_once()

    @patch("src.longbridge_provider.sync_longbridge_watchlist")
    def test_sync_longbridge_watchlist_uses_provider(self, sync_watchlist) -> None:
        sync_watchlist.return_value = {
            "classification_rule": "非现金流美股归 Growth",
            "growth_us_watchlist": [{"symbol": "NVDA.US", "name": "NVIDIA", "group_name": "us"}],
            "cash_anchor_us_watchlist": [{"symbol": "QQQI.US", "name": "QQQI"}],
            "ignored_non_us": [],
            "summary": {
                "growth_us_watch_items": 1,
                "cash_anchor_us_watch_items": 1,
                "ignored_non_us_watch_items": 0,
            },
        }

        reply = handle_command("/sync longbridge watchlist", "cli")

        self.assertIsNotNone(reply)
        self.assertIn("长桥自选股读取完成", reply or "")
        self.assertIn("NVDA.US", reply or "")
        self.assertIn("QQQI.US", reply or "")
        sync_watchlist.assert_called_once()

    @patch("src.longbridge_provider.apply_longbridge_cash_anchor_sync")
    def test_apply_longbridge_uses_provider(self, apply_sync) -> None:
        apply_sync.return_value = {
            "summary": {"updated_count": 1, "skipped_count": 2},
            "updated": [
                {
                    "symbol": "QQQI.US",
                    "name": "QQQI",
                    "shares": 10,
                    "cost_price": 50,
                    "current_price": 55,
                    "annual_dividend_per_share": 6,
                }
            ],
            "skipped": [],
        }
        reply = handle_command("/apply longbridge cash_anchor", "cli")
        self.assertIsNotNone(reply)
        self.assertIn("长桥持仓已写入", reply or "")
        self.assertIn("QQQI.US", reply or "")

    @patch("src.growth_portfolio.review_growth_symbol")
    def test_growth_review_uses_provider(self, review_symbol) -> None:
        review_symbol.return_value = "成长复盘"
        reply = handle_command("/growth-review NVDA.US", "cli")
        self.assertEqual(reply, "成长复盘")
        review_symbol.assert_called_once_with("NVDA.US", chat_id="cli")

    @patch("src.cash_anchor_watchlist.upsert_cash_watch_item")
    def test_cash_watchlist_batch_uses_provider(self, upsert_watch_item) -> None:
        upsert_watch_item.return_value = {
            "updated_watch_item": {"symbol": "600900.SH", "name": "长江电力"},
            "watch_action": "created",
        }
        reply = handle_command(
            "/cash-watchlist\n"
            "symbol=600900.SH name=长江电力 market=CN priority=high reason=核心红利 trigger=股息率回到目标区间",
            "cli",
        )
        self.assertIsNotNone(reply)
        self.assertIn("成功 1 条", reply or "")
        self.assertIn("600900.SH", reply or "")
        upsert_watch_item.assert_called_once()

    @patch("src.scheduler.runner.run_job_once")
    def test_scheduled_review_command_runs_dry_run_by_default(self, run_job_once) -> None:
        run_job_once.return_value = "试运行结果"
        reply = handle_command("/scheduled-review growth_us_close_review", "cli")

        self.assertEqual(reply, "试运行结果")
        self.assertTrue(run_job_once.call_args.kwargs["dry_run"])
        self.assertTrue(run_job_once.call_args.kwargs["send_result"] is False)

    @patch("src.scheduler.runner.run_job_once")
    def test_scheduled_review_command_can_execute(self, run_job_once) -> None:
        run_job_once.return_value = "正式结果"
        reply = handle_command("/scheduled-review growth_us_close_review execute=true", "cli")

        self.assertEqual(reply, "正式结果")
        self.assertFalse(run_job_once.call_args.kwargs["dry_run"])
        self.assertTrue(run_job_once.call_args.kwargs["send_result"] is False)

    @patch("src.growth_universe.sync_growth_universe")
    def test_growth_universe_command_uses_provider(self, sync_universe) -> None:
        sync_universe.return_value = {
            "classification_rule": "longbridge universe",
            "universe": [
                {
                    "symbol": "NVDA.US",
                    "name": "NVIDIA",
                    "asset_type": "stock",
                    "source_types": ["longbridge_watchlist"],
                    "source_groups": [],
                    "has_position": False,
                }
            ],
            "excluded": [],
            "summary": {
                "universe_count": 1,
                "source_positions": 0,
                "source_watch_items": 1,
                "option_contracts_mapped": 0,
                "excluded_cash_anchor": 0,
                "excluded_leveraged_etf": 0,
                "excluded_index": 0,
                "excluded_non_us": 0,
            },
        }

        reply = handle_command("/growth-universe", "cli")

        self.assertIsNotNone(reply)
        self.assertIn("Growth Engine 长桥 universe", reply or "")
        self.assertIn("NVDA.US", reply or "")

    @patch("src.research_dossier.refresh_dossier_facts")
    def test_dossier_refresh_uses_research_dossier_provider(self, refresh_dossier) -> None:
        refresh_dossier.return_value = {
            "status": "ok",
            "framework_id": "Cash_Anchor",
            "symbol": "600900",
            "path": "frameworks/Cash_Anchor/research_dossiers/600900.json",
            "last_fact_update_at": "2026-06-05T10:00:00",
            "item_counts": {"news": 1, "announcement": 1, "filing": 1},
            "warnings": [],
        }

        reply = handle_command("/dossier-refresh framework=Cash_Anchor symbol=600900 market=CN days=180", "cli")

        self.assertIsNotNone(reply)
        self.assertIn("研究档案事实刷新完成", reply or "")
        refresh_dossier.assert_called_once()
        self.assertEqual(refresh_dossier.call_args.kwargs["framework_id"], "Cash_Anchor")
        self.assertEqual(refresh_dossier.call_args.kwargs["symbol"], "600900")
        self.assertEqual(refresh_dossier.call_args.kwargs["market"], "CN")
        self.assertEqual(refresh_dossier.call_args.kwargs["days"], 180)

    def test_dossier_refresh_requires_framework(self) -> None:
        reply = handle_command("/dossier-refresh symbol=600900 market=CN", "cli")

        self.assertIsNotNone(reply)
        self.assertIn("用法：/dossier-refresh", reply or "")

    @patch("src.research_dossier.build_dossier_update_proposal")
    def test_update_dossier_alias_uses_research_dossier_proposal(self, build_proposal) -> None:
        build_proposal.return_value = {
            "status": "ok",
            "framework_id": "Cash_Anchor",
            "symbol": "600900",
            "path": "frameworks/Cash_Anchor/research_dossiers/600900.json",
            "existing_dossier": {
                "freshness": {"reason": "档案还没有事实更新时间。"},
            },
            "item_counts": {"news": 1, "announcement": 1, "filing": 1},
            "candidate_facts": [
                {
                    "fact_type_label": "利润分配候选",
                    "target_sections": ["fundamental_notes", "quantitative_checks", "evidence_log"],
                    "evidence": {
                        "title": "2025年度利润分配方案为10派8.2元",
                        "published_at": "2026-05-30",
                    },
                }
            ],
            "warnings": [],
        }

        reply = handle_command("/update-dossier framework=Cash_Anchor symbol=600900 market=CN days=180", "cli")

        self.assertIsNotNone(reply)
        self.assertIn("研究档案更新建议", reply or "")
        build_proposal.assert_called_once()
        self.assertEqual(build_proposal.call_args.kwargs["framework_id"], "Cash_Anchor")
        self.assertEqual(build_proposal.call_args.kwargs["symbol"], "600900")
        self.assertEqual(build_proposal.call_args.kwargs["market"], "CN")
        self.assertEqual(build_proposal.call_args.kwargs["days"], 180)


if __name__ == "__main__":
    unittest.main()
