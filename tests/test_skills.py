from __future__ import annotations

import json
import os
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
            skills.ensure_skill_allowed("Cash_Anchor", "hithink-usstock-selector")

    def test_news_search_without_key_returns_not_configured_payload(self) -> None:
        with patch.dict(os.environ, {"IWENCAI_API_KEY": ""}):
            loaded = skills.load_skill(
                "news-search",
                {"query": "AI 半导体 最新新闻"},
                framework_id="Growth_Engine",
                agent_role="worker",
            )
        payload = loaded.to_payload()["result"]

        self.assertEqual(payload["status"], "provider_not_configured")
        self.assertEqual(payload["source"], "iwencai_news_search")
        self.assertEqual(payload["data_type"], "news")
        self.assertIn("freshness", payload)
        self.assertIn("IWENCAI_API_KEY", payload["error"])

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
