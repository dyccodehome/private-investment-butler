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

    def test_cash_anchor_buy_output_appends_position_guardrail(self) -> None:
        state = AgentState(user_input="加仓600900，给我执行建议", framework_id="Cash_Anchor")
        state.context_bundle_id = "CN_Dividend_Income"
        state.draft_decision = "结论：可以考虑。关键事实：持仓已披露。风险：注意仓位。下一步：小额执行。"
        state.disclosed_data.append(
            DisclosureRecord(
                skill_name="portfolio_snapshot",
                arguments={"scope": "cash_anchor_dividend_retirement"},
                payload={
                    "result": {
                        "status": "ok",
                        "data_type": "portfolio_snapshot",
                        "data": {
                            "position_limit_analysis": {
                                "scope": "A股红利池",
                                "denominator_market_value": 100000,
                                "positions": [
                                    {
                                        "symbol": "600900",
                                        "weight": 0.2,
                                        "limit_pct": 0.15,
                                        "industry": "utility",
                                        "industry_label": "电力/公用事业",
                                        "can_add": False,
                                        "strict_max_add_market_value": 0,
                                        "add_guardrail": {
                                            "status": "over_limit",
                                            "can_add": False,
                                            "strict_max_add_market_value": 0,
                                            "binding_constraints": [
                                                {
                                                    "constraint_id": "single_position",
                                                    "label": "单票上限",
                                                    "status": "over_limit",
                                                    "max_add_market_value": 0,
                                                }
                                            ],
                                        },
                                    }
                                ],
                            }
                        },
                    }
                },
            )
        )

        apply_output_contract(state)

        self.assertEqual(state.output_contract["status"], "warn")
        self.assertEqual(state.output_contract["trade_guardrail"]["status"], "blocked")
        self.assertIn("仓位纪律校验", state.draft_decision)
        self.assertIn("严格可加额度：0 CNY", state.draft_decision)
        self.assertEqual(state.decision_snapshot["trade_guardrail"]["symbol"], "600900")


if __name__ == "__main__":
    unittest.main()
