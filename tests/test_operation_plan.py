from __future__ import annotations

import unittest
from datetime import date

from src.operation_plan import build_operation_framework_report, format_operation_framework_report


class OperationPlanTest(unittest.TestCase):
    def test_growth_allow_signal_builds_add_plan_candidate(self) -> None:
        report = build_operation_framework_report(
            framework_id="Growth_Engine",
            market="US",
            workflow_type="premarket",
            tracked_symbols=[],
            research_engine={
                "research_signals": [
                    {
                        "ticker": "NVDA.US",
                        "name": "NVIDIA",
                        "has_position": True,
                        "asset_type": "stock",
                        "thesis_impact": "strengthened",
                        "valuation_view": "above_ma120",
                        "risk_level": "medium",
                        "evidence_strength": "high",
                        "suggested_status": "add_condition_review",
                        "next_validation": ["数据中心收入增速"],
                    }
                ],
                "deep_research_queue": [],
            },
            as_of=date(2026, 6, 21),
        )

        plan = report["operation_plans"][0]
        self.assertEqual(plan["permission_result"], "ALLOW")
        self.assertEqual(plan["action"], "add_plan_candidate")
        self.assertEqual(plan["final_status"], "wait_for_user_approval")
        self.assertTrue(plan["user_approval_required"])

    def test_rejected_signal_maps_to_no_action(self) -> None:
        report = build_operation_framework_report(
            framework_id="Growth_Engine",
            market="US",
            workflow_type="close",
            tracked_symbols=[],
            research_engine={
                "research_signals": [
                    {
                        "ticker": "NET.US",
                        "name": "Cloudflare",
                        "has_position": False,
                        "thesis_impact": "weakened",
                        "valuation_view": "unknown",
                        "risk_level": "medium",
                        "evidence_strength": "medium",
                        "suggested_status": "downgrade_watch",
                    }
                ]
            },
        )

        plan = report["operation_plans"][0]
        self.assertEqual(plan["permission_result"], "REJECT")
        self.assertEqual(plan["action"], "no_action")
        self.assertEqual(plan["final_status"], "blocked")

    def test_format_operation_framework_report(self) -> None:
        report = build_operation_framework_report(
            framework_id="Cash_Anchor",
            market="CN",
            workflow_type="premarket",
            tracked_symbols=[{"symbol": "600900.SH", "name": "长江电力", "market": "CN", "source": "holding"}],
            market_data={"600900.SH": {"status": "ok", "data": {"current_price": 30}}},
        )

        text = format_operation_framework_report(report)

        self.assertIn("Operation Framework", text)
        self.assertIn("600900.SH", text)
        self.assertIn("hold_review", text)


if __name__ == "__main__":
    unittest.main()
