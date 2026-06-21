from __future__ import annotations

import unittest
from datetime import date

from src.research_engine import build_growth_research_report, format_growth_research_report


class ResearchEngineTest(unittest.TestCase):
    def test_build_growth_research_report_creates_signals_and_queue(self) -> None:
        report = build_growth_research_report(
            universe_payload={
                "summary": {"universe_count": 2},
                "universe": [
                    {
                        "symbol": "NVDA.US",
                        "name": "NVIDIA",
                        "asset_type": "stock",
                        "has_position": True,
                        "current_price": 950,
                        "cost_price": 900,
                    },
                    {
                        "symbol": "NET.US",
                        "name": "Cloudflare",
                        "asset_type": "stock",
                        "has_position": False,
                    },
                ],
            },
            symbol_intel={
                "NVDA.US": {
                    "news": {
                        "items": [
                            {
                                "title": "NVIDIA data center growth beats expectations",
                                "summary": "AI compute demand remains strong.",
                            }
                        ]
                    }
                },
                "NET.US": {
                    "news": {
                        "items": [
                            {
                                "title": "Cloudflare launches new zero trust AI security product",
                                "summary": "Enterprise security platform expands.",
                            }
                        ]
                    }
                },
            },
            research_dossiers={
                "NVDA.US": {
                    "exists": True,
                    "freshness": {"stale": False},
                    "core_thesis": "AI GPU and accelerated compute leader.",
                    "open_questions": ["数据中心收入能否继续高增"],
                },
                "NET.US": {
                    "exists": False,
                    "freshness": {"stale": False},
                },
            },
            market_data={},
            as_of=date(2026, 6, 16),
            fetch_missing_context=False,
        )

        self.assertEqual(report["engine"], "growth_research_mvp")
        self.assertEqual(report["analyzed_symbol_count"], 2)
        signals = {item["ticker"]: item for item in report["research_signals"]}
        self.assertEqual(signals["NVDA.US"]["theme_id"], "ai_compute")
        self.assertEqual(signals["NVDA.US"]["thesis_impact"], "strengthened")
        self.assertTrue(report["theme_radar"])
        queue = {item["ticker"]: item for item in report["deep_research_queue"]}
        self.assertEqual(queue["NET.US"]["suggested_action"], "create_dossier")
        self.assertIn("NET.US 未建立研究档案。", report["data_quality"]["limitations"])

    def test_format_growth_research_report(self) -> None:
        report = {
            "as_of": "2026-06-16",
            "universe_count": 1,
            "analyzed_symbol_count": 1,
            "data_quality": {"status": "ok", "limitations": []},
            "theme_radar": [
                {
                    "theme": "AI 算力与加速计算",
                    "thesis_impact": "strengthened",
                    "signal_count": 1,
                    "holding_count": 1,
                    "related_symbols": ["NVDA.US"],
                }
            ],
            "research_signals": [
                {
                    "ticker": "NVDA.US",
                    "name": "NVIDIA",
                    "theme": "AI 算力与加速计算",
                    "thesis_impact": "strengthened",
                    "suggested_status": "hold_review",
                    "evidence_strength": "high",
                }
            ],
            "deep_research_queue": [],
        }

        text = format_growth_research_report(report)

        self.assertIn("Growth Engine 投研雷达", text)
        self.assertIn("NVDA.US", text)
        self.assertIn("Research Signals", text)


if __name__ == "__main__":
    unittest.main()
