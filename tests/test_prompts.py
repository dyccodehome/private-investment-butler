from __future__ import annotations

import unittest

from src import prompts


class PromptsTest(unittest.TestCase):
    def test_worker_prompt_renders_template_values(self) -> None:
        text = prompts.worker_user_prompt(
            framework_id="Cash_Anchor",
            context_bundle_id="CN_Dividend_Income",
            loaded_context_files=["constitution.md"],
            strategy_context="策略上下文",
            user_input="用户输入",
            disclosed_data_names="snapshot",
            disclosed_data="{}",
        )

        self.assertIn("Cash_Anchor", text)
        self.assertIn("用户输入", text)
        self.assertNotIn("{{", text)

    def test_system_prompt_includes_shared_response_style(self) -> None:
        text = prompts.growth_review_system_prompt()

        self.assertIn("Growth_Engine", text)
        self.assertIn("措辞准确、简洁、中性", text)
        self.assertNotIn("{{", text)

    def test_auditor_persona_selects_dynamic_section(self) -> None:
        risk = prompts.auditor_system_prompt("risk", risk_persona="risk", purist_persona="purist")
        purist = prompts.auditor_system_prompt("purist", risk_persona="risk", purist_persona="purist")
        neutral = prompts.auditor_system_prompt("neutral", risk_persona="risk", purist_persona="purist")

        self.assertIn("回撤和仓位风险", risk)
        self.assertIn("规则变更是否过拟合", purist)
        self.assertIn("中性但严格", neutral)


if __name__ == "__main__":
    unittest.main()
