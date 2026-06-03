from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import budget_manager


class BudgetManagerTest(unittest.TestCase):
    def test_workflow_for_call_site(self) -> None:
        self.assertEqual(
            budget_manager.workflow_for_call_site("growth_portfolio.review"),
            "growth_daily_review",
        )
        self.assertEqual(
            budget_manager.workflow_for_call_site("sub_agent.stage_two_decide"),
            "natural_language_pipeline",
        )

    def test_trace_token_total_reads_usage_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            token_dir = Path(tmp)
            (token_dir / "2026-06-03.jsonl").write_text(
                json.dumps({"trace_id": "trace_a", "total_tokens": 100}, ensure_ascii=False)
                + "\n"
                + json.dumps({"trace_id": "trace_b", "total_tokens": 20}, ensure_ascii=False)
                + "\n",
                encoding="utf-8",
            )

            with patch.object(budget_manager, "TOKEN_USAGE_DIR", token_dir):
                total = budget_manager.trace_token_total("trace_a", date="2026-06-03")

        self.assertEqual(total, 100)


if __name__ == "__main__":
    unittest.main()
