from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.research_dossier import (
    append_user_action_to_dossier,
    build_dossier_update_proposal,
    build_dossier_update_proposal_from_disclosures,
    extract_symbol,
    format_dossier_update_proposal,
    format_dossier_update_proposal_notice,
    refresh_dossier_facts,
    stale_dossier_notice_from_disclosures,
)
from src.state import DisclosureRecord


class ResearchDossierTest(unittest.TestCase):
    def test_extracts_cn_symbol_next_to_chinese_text(self) -> None:
        text = "我现在情绪上头，想不看财报直接满仓买入600900，突破仓位上限也可以"

        self.assertEqual(extract_symbol(text), "600900")

    def test_does_not_treat_a_share_prefix_as_us_ticker(self) -> None:
        self.assertIsNone(extract_symbol("A股半导体成长股跌破 MA120 怎么处理"))

    def test_append_user_action_extracts_symbol_from_audit_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch("src.research_dossier.FRAMEWORKS_DIR", Path(tmpdir)):
            path = append_user_action_to_dossier(
                chat_id="oc_1",
                framework_id="Cash_Anchor",
                user_action="user_clicked_abandon_operation",
                final_reply_to_user="已记录：用户接受审计意见，放弃本次操作。",
                reason="审计未通过：600900 满仓请求不符合仓位规则。",
            )

            self.assertIsNotNone(path)
            data = json.loads(Path(path or "").read_text(encoding="utf-8"))
            self.assertEqual(data["symbol"], "600900")
            self.assertEqual(data["decision_log"][0]["user_action"], "user_clicked_abandon_operation")
            self.assertEqual(data["decision_log"][0]["decision_snapshot"]["action_type"], "human_abandon")

    def test_refresh_dossier_facts_updates_fact_time_when_sources_have_items(self) -> None:
        payload_with_item = {
            "status": "ok",
            "source": "market_intel_news",
            "data_type": "news",
            "data": {
                "items": [
                    {
                        "title": "长江电力年度报告",
                        "published_at": "2026-05-01",
                        "url": "https://example.com/report",
                    }
                ]
            },
            "source_chain": [{"provider": "fixture", "status": "ok"}],
            "error": "",
        }
        payload_empty = {
            "status": "empty",
            "source": "market_intel_announcements",
            "data_type": "announcement",
            "data": {"items": []},
            "source_chain": [{"provider": "fixture", "status": "empty"}],
            "error": "empty",
        }
        with tempfile.TemporaryDirectory() as tmpdir, patch("src.research_dossier.FRAMEWORKS_DIR", Path(tmpdir)), patch(
            "src.market_intel.fetch_company_news", return_value=payload_with_item
        ), patch("src.market_intel.fetch_company_announcements", return_value=payload_empty), patch(
            "src.market_intel.fetch_filings", return_value=payload_empty
        ):
            result = refresh_dossier_facts(framework_id="Cash_Anchor", symbol="600900", market="CN")

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["item_counts"]["news"], 1)
            self.assertTrue(result["last_fact_update_at"])
            data = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
            self.assertEqual(data["last_fact_update_at"], result["last_fact_update_at"])
            self.assertEqual(data["evidence_log"][0]["item_counts"]["news"], 1)

    def test_refresh_dossier_facts_keeps_fact_time_empty_when_all_sources_missing(self) -> None:
        payload_empty = {
            "status": "empty",
            "source": "market_intel_news",
            "data_type": "news",
            "data": {"items": []},
            "source_chain": [{"provider": "fixture", "status": "empty"}],
            "error": "empty",
        }
        with tempfile.TemporaryDirectory() as tmpdir, patch("src.research_dossier.FRAMEWORKS_DIR", Path(tmpdir)), patch(
            "src.market_intel.fetch_company_news", return_value=payload_empty
        ), patch("src.market_intel.fetch_company_announcements", return_value=payload_empty), patch(
            "src.market_intel.fetch_filings", return_value=payload_empty
        ):
            result = refresh_dossier_facts(framework_id="Cash_Anchor", symbol="600900", market="CN")

            self.assertEqual(result["status"], "missing")
            self.assertEqual(result["last_fact_update_at"], "")
            self.assertTrue(result["freshness"]["is_stale"])

    def test_build_dossier_update_proposal_does_not_write_dossier(self) -> None:
        news_payload = {
            "status": "ok",
            "source": "market_intel_news",
            "data_type": "news",
            "data": {
                "items": [
                    {
                        "title": "长江电力近期经营保持稳定",
                        "summary": "新闻线索，需继续核验正式公告。",
                        "published_at": "2026-06-01",
                        "source": "fixture news",
                        "url": "https://example.com/news",
                    }
                ]
            },
            "source_chain": [{"provider": "fixture", "status": "ok"}],
            "error": "",
        }
        announcement_payload = {
            "status": "ok",
            "source": "market_intel_announcements",
            "data_type": "announcement",
            "data": {
                "items": [
                    {
                        "symbol": "600900",
                        "name": "长江电力",
                        "title": "2025年度利润分配方案为10派8.2元",
                        "category": "利润分配",
                        "published_at": "2026-05-30",
                        "source": "东方财富公告",
                        "url": "https://example.com/dividend",
                    }
                ]
            },
            "source_chain": [{"provider": "fixture", "status": "ok"}],
            "error": "",
        }
        filing_payload = {
            "status": "ok",
            "source": "market_intel_filings",
            "data_type": "filing",
            "data": {
                "items": [
                    {
                        "symbol": "600900",
                        "name": "长江电力",
                        "title": "长江电力2025年年度报告",
                        "category": "财务报告",
                        "published_at": "2026-05-30",
                        "source": "东方财富公告",
                        "url": "https://example.com/report",
                    }
                ]
            },
            "source_chain": [{"provider": "fixture", "status": "ok"}],
            "error": "",
        }
        with tempfile.TemporaryDirectory() as tmpdir, patch("src.research_dossier.FRAMEWORKS_DIR", Path(tmpdir)), patch(
            "src.market_intel.fetch_company_news", return_value=news_payload
        ), patch("src.market_intel.fetch_company_announcements", return_value=announcement_payload), patch(
            "src.market_intel.fetch_filings", return_value=filing_payload
        ):
            proposal = build_dossier_update_proposal(framework_id="Cash_Anchor", symbol="600900", market="CN")

            self.assertEqual(proposal["status"], "ok")
            self.assertEqual(proposal["write_policy"], "proposal_only_no_auto_write")
            self.assertFalse(Path(proposal["path"]).exists())
            self.assertEqual(proposal["item_counts"], {"news": 1, "announcement": 1, "filing": 1})
            fact_types = {item["fact_type"] for item in proposal["candidate_facts"]}
            self.assertIn("financial_report", fact_types)
            self.assertIn("profit_distribution", fact_types)
            self.assertIn("evidence_log", proposal["proposed_dossier_patch"])

            formatted = format_dossier_update_proposal(proposal)

        self.assertIn("研究档案更新建议", formatted)
        self.assertIn("未自动写入", formatted)

    def test_build_dossier_update_proposal_from_existing_disclosures(self) -> None:
        proposal = build_dossier_update_proposal_from_disclosures(
            [
                DisclosureRecord(
                    skill_name="research_dossier",
                    payload={
                        "result": {
                            "data": {
                                "framework_id": "Cash_Anchor",
                                "symbol": "600900",
                                "path": "frameworks/Cash_Anchor/research_dossiers/600900.json",
                                "exists": True,
                                "freshness": {"is_stale": True, "reason": "档案还没有事实更新时间。"},
                                "dossier": {
                                    "company_name": "长江电力",
                                    "last_fact_update_at": "",
                                },
                            }
                        }
                    },
                ),
                DisclosureRecord(
                    skill_name="news-search",
                    payload={
                        "result": {
                            "status": "ok",
                            "source": "market_intel_news",
                            "data_type": "news",
                            "data": {
                                "items": [
                                    {
                                        "title": "长江电力经营新闻",
                                        "published_at": "2026-06-01",
                                        "source": "fixture news",
                                    }
                                ]
                            },
                            "source_chain": [],
                            "error": "",
                        }
                    },
                ),
                DisclosureRecord(
                    skill_name="announcement-search",
                    payload={
                        "result": {
                            "status": "ok",
                            "source": "market_intel_announcements",
                            "data_type": "announcement",
                            "data": {
                                "items": [
                                    {
                                        "title": "2025年度利润分配方案为10派8.2元",
                                        "category": "利润分配",
                                        "published_at": "2026-05-30",
                                        "source": "东方财富公告",
                                    }
                                ]
                            },
                            "source_chain": [],
                            "error": "",
                        }
                    },
                ),
            ]
        )

        self.assertIsNotNone(proposal)
        assert proposal is not None
        self.assertEqual(proposal["status"], "ok")
        self.assertEqual(proposal["item_counts"]["announcement"], 1)
        self.assertIn("profit_distribution", {item["fact_type"] for item in proposal["candidate_facts"]})

        notice = format_dossier_update_proposal_notice(proposal)
        self.assertIn("研究档案更新候选", notice)
        self.assertIn("/review-dossier framework=Cash_Anchor symbol=600900", notice)

    def test_stale_notice_reads_research_dossier_disclosure(self) -> None:
        notice = stale_dossier_notice_from_disclosures(
            [
                DisclosureRecord(
                    skill_name="research_dossier",
                    payload={
                        "result": {
                            "freshness": {
                                "is_stale": True,
                                "reason": "档案还没有事实更新时间。",
                            },
                            "data": {
                                "symbol": "NVDA",
                                "framework_id": "Growth_Engine",
                            }
                        }
                    },
                )
            ]
        )

        self.assertIn("NVDA", notice)
        self.assertIn("/review-dossier framework=Growth_Engine symbol=NVDA", notice)


if __name__ == "__main__":
    unittest.main()
