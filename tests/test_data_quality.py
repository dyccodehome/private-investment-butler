from __future__ import annotations

import unittest

from src.data_quality import payload_data_quality, summarize_disclosures
from src.state import DisclosureRecord


class DataQualityTest(unittest.TestCase):
    def test_payload_quality_marks_provider_gap(self) -> None:
        quality = payload_data_quality(
            {
                "status": "provider_not_configured",
                "source": "market_intel_news",
                "data_type": "news",
                "data": {"items": []},
                "freshness": {"stale": False},
                "warnings": [],
                "error": "missing key",
            }
        )

        self.assertEqual(quality["coverage"]["news"], "missing")
        self.assertIn("missing key", quality["limitations"])

    def test_summarize_disclosures_merges_quality_blocks(self) -> None:
        disclosure = DisclosureRecord(
            skill_name="news-search",
            payload={
                "result": {
                    "status": "provider_not_configured",
                    "source": "market_intel_news",
                    "data_type": "news",
                    "data": {},
                    "freshness": {"stale": False},
                    "warnings": [],
                    "error": "missing key",
                }
            },
        )

        summary = summarize_disclosures([disclosure])

        self.assertEqual(summary["coverage"]["news"], "missing")
        self.assertEqual(summary["stale_or_unknown_blocks"], ["news"])

    def test_summarize_disclosures_marks_is_stale_freshness(self) -> None:
        disclosure = DisclosureRecord(
            skill_name="research_dossier",
            payload={
                "result": {
                    "status": "ok",
                    "source": "local",
                    "data_type": "research_dossier",
                    "data": {},
                    "freshness": {"is_stale": True, "reason": "档案还没有事实更新时间。"},
                    "warnings": [],
                    "error": "",
                }
            },
        )

        summary = summarize_disclosures([disclosure])

        self.assertEqual(summary["coverage"]["research_dossier"], "ok")
        self.assertEqual(summary["stale_or_unknown_blocks"], ["research_dossier"])


if __name__ == "__main__":
    unittest.main()
