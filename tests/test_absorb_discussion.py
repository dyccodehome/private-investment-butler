from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import absorb_discussion
from src.knowledge_absorber import PatchProposal, load_patch_proposal, save_patch_proposal


class AbsorbDiscussionTest(unittest.TestCase):
    def test_discussion_turn_calls_llm_with_context_and_updates_patch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frameworks = root / "frameworks"
            target_dir = frameworks / "Cash_Anchor"
            target_dir.mkdir(parents=True)
            (target_dir / "constitution.md").write_text("旧宪法内容", encoding="utf-8")
            proposal = PatchProposal(
                patch_id="CASH-TEST",
                framework_id="Cash_Anchor",
                target_id="Cash_Anchor",
                target_file="constitution.md",
                target_name="现金流总框架",
                target_section="旧条文",
                patch_markdown="初版补丁",
                auditor_opinion="初版审计",
                discussion_log=[{"role": "system", "content": "开始讨论", "created_at": "2026-01-01T00:00:00"}],
            )

            with patch("src.knowledge_absorber.FRAMEWORKS_DIR", frameworks):
                save_patch_proposal(proposal)

            raw = json.dumps(
                {
                    "status": "ready_to_accept",
                    "reply_to_user": "可以加入，但需要用户回复同意。",
                    "updated_patch_markdown": "修订后补丁",
                    "updated_target_section": "旧条文",
                    "decision_reason": "适用边界已明确",
                    "next_question": "",
                },
                ensure_ascii=False,
            )

            with patch("src.knowledge_absorber.FRAMEWORKS_DIR", frameworks), patch(
                "src.absorb_discussion.LLMClient"
            ) as client_cls:
                client_cls.for_agent.return_value.complete.return_value = raw
                result = absorb_discussion.run_absorb_discussion_turn(
                    framework_id="Cash_Anchor",
                    patch_id="CASH-TEST",
                    user_message="只适用于买入前筛选",
                    chat_id="cli",
                )
                updated = load_patch_proposal("Cash_Anchor", "CASH-TEST")

        self.assertEqual(result.status, "ready_to_accept")
        self.assertEqual(updated.patch_markdown, "修订后补丁")
        self.assertEqual(updated.human_decision, "ready_to_accept")
        self.assertEqual(updated.discussion_log[-1]["role"], "assistant")
        prompt = client_cls.for_agent.return_value.complete.call_args.kwargs["user_prompt"]
        self.assertIn("旧宪法内容", prompt)
        self.assertIn("只适用于买入前筛选", prompt)


if __name__ == "__main__":
    unittest.main()
