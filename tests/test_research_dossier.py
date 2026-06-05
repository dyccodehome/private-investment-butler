from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.research_dossier import (
    append_user_action_to_dossier,
    extract_symbol,
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

    def test_stale_notice_reads_research_dossier_disclosure(self) -> None:
        notice = stale_dossier_notice_from_disclosures(
            [
                DisclosureRecord(
                    skill_name="research_dossier",
                    payload={
                        "result": {
                            "data": {
                                "symbol": "NVDA",
                                "framework_id": "Growth_Engine",
                                "freshness": {
                                    "is_stale": True,
                                    "reason": "档案还没有事实更新时间。",
                                },
                            }
                        }
                    },
                )
            ]
        )

        self.assertIn("NVDA", notice)
        self.assertIn("/dossier-refresh framework=Growth_Engine symbol=NVDA", notice)


if __name__ == "__main__":
    unittest.main()
