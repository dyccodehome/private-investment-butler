from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import skills


class SkillsTest(unittest.TestCase):
    def setUp(self) -> None:
        skills.SKILL_REGISTRY = {}

    def test_framework_skill_allowlist_is_enforced(self) -> None:
        spec = skills.ensure_skill_allowed("Cash_Anchor", "portfolio_snapshot")

        self.assertEqual(spec.skill_id, "portfolio_snapshot")
        with self.assertRaises(PermissionError):
            skills.ensure_skill_allowed("Growth_Engine", "portfolio_snapshot")

    def test_news_search_uses_market_intel_provider(self) -> None:
        with patch("src.skills.fetch_company_news") as fetch_news:
            fetch_news.return_value = {
                "status": "provider_not_configured",
                "source": "market_intel_news",
                "data_type": "news",
                "data": {"query": "AI 半导体 最新新闻", "items": []},
                "freshness": {"as_of": "2026-06-05T10:00:00", "stale": False, "stale_reason": ""},
                "warnings": [],
                "error": "缺少 akshare，未执行 A 股东方财富新闻源。",
            }
            loaded = skills.load_skill(
                "news-search",
                {"query": "AI 半导体 最新新闻"},
                framework_id="Growth_Engine",
                agent_role="worker",
            )
        payload = loaded.to_payload()["result"]

        self.assertEqual(payload["status"], "provider_not_configured")
        self.assertEqual(payload["source"], "market_intel_news")
        self.assertEqual(payload["data_type"], "news")
        self.assertIn("freshness", payload)
        self.assertIn("data_quality", payload)
        self.assertEqual(payload["data_quality"]["coverage"]["news"], "missing")
        self.assertIn("akshare", payload["error"])
        fetch_news.assert_called_once_with(
            "AI 半导体 最新新闻",
            market="",
            query="AI 半导体 最新新闻",
            limit=10,
        )

    def test_announcement_search_uses_market_intel_provider(self) -> None:
        with patch("src.skills.fetch_company_announcements") as fetch_announcements:
            fetch_announcements.return_value = {
                "status": "provider_not_configured",
                "source": "market_intel_announcements",
                "data_type": "announcement",
                "data": {"query": "600900 长江电力 年报 分红", "items": []},
                "freshness": {"as_of": "2026-06-05T10:00:00", "stale": False, "stale_reason": ""},
                "warnings": [],
                "error": "缺少 akshare，未执行 A 股东方财富公告源。",
            }
            loaded = skills.load_skill(
                "announcement-search",
                {"query": "600900 长江电力 年报 分红"},
                framework_id="Cash_Anchor",
                agent_role="worker",
            )
        payload = loaded.to_payload()["result"]

        self.assertEqual(payload["status"], "provider_not_configured")
        self.assertEqual(payload["source"], "market_intel_announcements")
        self.assertEqual(payload["data_type"], "announcement")
        self.assertIn("data_quality", payload)
        self.assertEqual(payload["data_quality"]["coverage"]["announcement"], "missing")
        self.assertIn("akshare", payload["error"])
        fetch_announcements.assert_called_once_with(
            "600900",
            market="",
            query="600900 长江电力 年报 分红",
            limit=10,
            days=30,
        )

    def test_trade_history_reads_local_chat_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            frameworks = Path(tmp) / "frameworks"
            history_dir = frameworks / "Growth_Engine" / "chat_history"
            history_dir.mkdir(parents=True)
            (history_dir / "2026-06-03.jsonl").write_text(
                json.dumps(
                    {
                        "timestamp": "2026-06-03 10:00:00",
                        "framework_id": "Growth_Engine",
                        "context_bundle_id": "US_Disruptive_Growth",
                        "user_query": "NVDA 回撤后要不要加仓",
                        "audit_signal": "WARN",
                        "status": "completed",
                        "final_reply_to_user": "继续观察 NVDA 的估值消化和业绩兑现。",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            with patch.object(skills, "FRAMEWORKS_DIR", frameworks):
                payload = skills._execute_skill_payload(
                    "trade_history",
                    {"framework_id": "Growth_Engine", "symbol": "NVDA"},
                )

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["data"]["match_count"], 1)
        self.assertEqual(payload["data"]["matches"][0]["source"], "chat_history")


if __name__ == "__main__":
    unittest.main()
