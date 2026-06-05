from __future__ import annotations

import unittest

from src.auditor import DOOMER_PERSONA, PURIST_PERSONA, _format_pass, _select_persona
from src.state import AgentState, DebateEntry


class AuditorFormattingTest(unittest.TestCase):
    def test_pass_format_hides_full_audit_log(self) -> None:
        state = AgentState(user_input="红利持仓今年分红怎么看")
        state.draft_decision = "先看到账流水，再看公告口径。"
        state.audit_signal = "PASS"
        state.audit_log.append(
            DebateEntry(
                role="auditor",
                content="[ALLOW]\n1. 宪法一致性\n通过\n5. 审计结论\n可以放行",
                verdict="PASS",
            )
        )

        reply = _format_pass(state)

        self.assertEqual(reply, "先看到账流水，再看公告口径。")
        self.assertNotIn("审计记录", reply)
        self.assertNotIn("[ALLOW]", reply)

    def test_buy_intent_uses_risk_audit_even_when_draft_mentions_rules(self) -> None:
        state = AgentState(user_input="满仓买入600900，直接给我执行建议")
        state.draft_decision = "拒绝执行，因为这违反 Cash Anchor 框架规则。"

        self.assertEqual(_select_persona(state), DOOMER_PERSONA)

    def test_explicit_constitution_change_uses_rule_change_audit(self) -> None:
        state = AgentState(user_input="/absorb Cash_Anchor 修改规则：买入前必须看财报")
        state.draft_decision = "生成补丁提案。"

        self.assertEqual(_select_persona(state), PURIST_PERSONA)


if __name__ == "__main__":
    unittest.main()
