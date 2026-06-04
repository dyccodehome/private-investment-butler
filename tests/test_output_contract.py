from __future__ import annotations

import unittest

from src.output_contract import apply_output_contract, validate_draft_decision
from src.state import AgentState, DisclosureRecord


class OutputContractTest(unittest.TestCase):
    def test_validate_draft_decision_detects_missing_sections(self) -> None:
        contract = validate_draft_decision("结论：维持。风险：估值仍高。")

        self.assertEqual(contract["status"], "warn")
        self.assertIn("facts", contract["missing_sections"])
        self.assertIn("next_action", contract["missing_sections"])

    def test_apply_output_contract_builds_historical_snapshot(self) -> None:
        state = AgentState(user_input="NVDA 要不要加仓", framework_id="Growth_Engine")
        state.context_bundle_id = "US_Disruptive_Growth"
        state.draft_decision = "结论：先观察。关键事实：行情已披露。风险：估值仍高。下一步：等财报。"
        state.disclosed_data.append(
            DisclosureRecord(
                skill_name="trade_history",
                payload={
                    "result": {
                        "status": "ok",
                        "source": "local_trade_history",
                        "data_type": "trade_history",
                        "data": {
                            "matches": [
                                {
                                    "source": "chat_history",
                                    "framework_id": "Growth_Engine",
                                    "timestamp": "2026-06-03 10:00:00",
                                    "audit_signal": "WARN",
                                    "status": "completed",
                                    "final_reply_preview": "继续观察。",
                                }
                            ]
                        },
                        "freshness": {"stale": False},
                        "warnings": [],
                        "error": "",
                    }
                },
            )
        )

        apply_output_contract(state)

        self.assertEqual(state.output_contract["status"], "ok")
        self.assertEqual(state.decision_snapshot["symbol"], "NVDA")
        self.assertEqual(state.decision_snapshot["action_type"], "add")
        history = state.decision_snapshot["historical_judgment_snapshot"]
        self.assertEqual(history["match_count"], 1)


if __name__ == "__main__":
    unittest.main()
