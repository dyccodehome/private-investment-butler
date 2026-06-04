from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.review_stats import decision_review_summary, load_decision_records


class ReviewStatsTest(unittest.TestCase):
    def test_decision_review_summary_counts_contract_and_quality(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            decision_dir = Path(tmp)
            (decision_dir / "2026-06-04.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "framework_id": "Growth_Engine",
                                "context_bundle_id": "US_Disruptive_Growth",
                                "decision_type": "growth_review",
                                "audit_signal": "WARN",
                                "status": "completed",
                                "decision_snapshot": {"symbol": "NVDA", "action_type": "watch"},
                                "output_contract": {"status": "ok", "missing_sections": []},
                                "data_quality_summary": {
                                    "coverage": {"news": "missing"},
                                    "stale_or_unknown_blocks": ["news"],
                                    "limitations": ["missing key"],
                                },
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {
                                "framework_id": "Cash_Anchor",
                                "decision_type": "audit_rejected",
                                "audit_signal": "REJECT",
                                "circuit_breaker": "triggered",
                                "requires_human_approval": True,
                                "status": "audit_rejected",
                                "decision_snapshot": {"symbol": "600900.SH", "action_type": "buy"},
                                "output_contract": {"status": "warn", "missing_sections": ["risk"]},
                                "data_quality_summary": {"coverage": {}, "stale_or_unknown_blocks": []},
                            },
                            ensure_ascii=False,
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            records = load_decision_records(date="2026-06-04", decision_dir=decision_dir)
            summary = decision_review_summary(date="2026-06-04", decision_dir=decision_dir)

        self.assertEqual(len(records), 2)
        self.assertEqual(summary["by_framework"]["Growth_Engine"], 1)
        self.assertEqual(summary["by_action_type"]["watch"], 1)
        self.assertEqual(summary["rejected_count"], 1)
        self.assertEqual(summary["contract"]["missing_sections"]["risk"], 1)
        self.assertEqual(summary["data_quality"]["stale_or_unknown_blocks"]["news"], 1)


if __name__ == "__main__":
    unittest.main()
