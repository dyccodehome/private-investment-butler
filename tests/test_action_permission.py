from __future__ import annotations

import unittest
from datetime import date

from src.action_permission import build_action_permission_report


class ActionPermissionTest(unittest.TestCase):
    def test_growth_signal_maps_to_allow_with_constraints(self) -> None:
        report = build_action_permission_report(
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
                        "thesis_impact": "strengthened",
                        "valuation_view": "above_ma120",
                        "risk_level": "medium",
                        "evidence_strength": "high",
                        "suggested_status": "add_condition_review",
                    }
                ],
                "deep_research_queue": [],
            },
            as_of=date(2026, 6, 21),
        )

        permission = report["permissions"][0]
        self.assertEqual(permission["permission_result"], "ALLOW")
        self.assertEqual(permission["permission_scope"], "draft_limited_plan")
        self.assertTrue(permission["requires_human_approval"])

    def test_growth_weakened_watch_signal_is_rejected(self) -> None:
        report = build_action_permission_report(
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

        permission = report["permissions"][0]
        self.assertEqual(permission["permission_result"], "REJECT")
        self.assertIn("thesis_weakened", permission["risk_flags"])

    def test_cash_holding_with_missing_market_data_warns(self) -> None:
        report = build_action_permission_report(
            framework_id="Cash_Anchor",
            market="CN",
            workflow_type="premarket",
            tracked_symbols=[
                {
                    "symbol": "600900.SH",
                    "name": "长江电力",
                    "market": "CN",
                    "source": "holding",
                }
            ],
            market_data={},
            data_gaps=["600900.SH 行情缺失。"],
        )

        permission = report["permissions"][0]
        self.assertEqual(permission["permission_result"], "WARN")
        self.assertEqual(permission["permission_scope"], "hold_with_data_gap")
        self.assertIn("market_data_missing", permission["risk_flags"])


if __name__ == "__main__":
    unittest.main()
