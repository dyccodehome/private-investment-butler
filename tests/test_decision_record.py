from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.decision_record import build_decision_record, save_decision_record
from src.state import AgentState, PipelineStatus


class DecisionRecordTest(unittest.TestCase):
    def test_build_decision_record_marks_audit_rejection(self) -> None:
        state = AgentState(user_input="NVDA 要不要加仓", chat_id="cli", framework_id="Growth_Engine")
        state.status = PipelineStatus.AUDIT_REJECTED
        state.final_answer = "流程已暂停"
        state.audit_signal = "REJECT"

        record = build_decision_record(state, created_at="2026-06-03T10:00:00")

        self.assertTrue(record.requires_human_approval)
        self.assertEqual(record.circuit_breaker, "triggered")
        self.assertIn("auto_execute_without_human_approval", record.forbidden_actions)

    def test_save_decision_record_writes_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "decisions"
            state = AgentState(user_input="红利持仓怎么看", chat_id="cli", framework_id="Cash_Anchor")
            state.status = PipelineStatus.COMPLETED
            state.final_answer = "观察"

            with patch("src.decision_record.DECISION_DIR", path):
                saved_path = save_decision_record(state)

            row = json.loads(saved_path.read_text(encoding="utf-8").splitlines()[0])

        self.assertEqual(row["framework_id"], "Cash_Anchor")
        self.assertEqual(row["decision_type"], "cash_anchor_review")


if __name__ == "__main__":
    unittest.main()
