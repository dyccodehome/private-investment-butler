from __future__ import annotations

import unittest

from src.auditor import _format_pass
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


if __name__ == "__main__":
    unittest.main()
