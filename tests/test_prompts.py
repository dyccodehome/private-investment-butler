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
        self.assertIn("投资管家", text)
        self.assertIn("不要输出 Markdown 表格", text)
        self.assertNotIn("{{", text)

    def test_worker_prompt_uses_concise_user_style(self) -> None:
        text = prompts.worker_user_prompt(
            framework_id="Cash_Anchor",
            context_bundle_id="CN_Dividend_Income",
            loaded_context_files=["constitution.md"],
            strategy_context="策略上下文",
            user_input="红利持仓今年分红怎么看",
            disclosed_data_names="portfolio_snapshot",
            disclosed_data="{}",
        )

        self.assertIn("不要套用", text)
        self.assertIn("不要输出 Markdown 表格", text)

    def test_worker_system_prompt_requires_position_guardrail_for_adds(self) -> None:
        text = prompts.worker_system_prompt()

        self.assertIn("position_limit_analysis", text)
        self.assertIn("strict_max_add_market_value", text)
        self.assertIn("买入后 A 股红利池市值分母", text)

    def test_auditor_persona_selects_dynamic_section(self) -> None:
        risk = prompts.auditor_system_prompt("risk", risk_persona="risk", purist_persona="purist")
        purist = prompts.auditor_system_prompt("purist", risk_persona="risk", purist_persona="purist")
        neutral = prompts.auditor_system_prompt("neutral", risk_persona="risk", purist_persona="purist")

        self.assertIn("回撤和仓位风险", risk)
        self.assertIn("规则变更是否过拟合", purist)
        self.assertIn("中性但严格", neutral)

    def test_scheduled_review_prompt_is_prompt_first_contract(self) -> None:
        system = prompts.scheduled_review_system_prompt()
        user = prompts.scheduled_review_user_prompt(
            framework_id="Growth_Engine",
            market="US",
            workflow_type="close",
            review_date="2026-06-22",
            context_json='{"tracked_symbols":[]}',
        )

        self.assertIn("Prompt path: prompts/scheduled_review/system.md", system)
        self.assertIn("Prompt path: prompts/scheduled_review/user.md", user)
        self.assertIn("prompt-first", system)
        self.assertIn("结构化判断摘要", system)
        self.assertIn("正式报告", system)
        self.assertIn("report_meta", system)
        self.assertIn("action_queue", system)
        self.assertIn("continuity_check", system)
        self.assertIn("position_reviews", system)
        self.assertIn("data_gaps", system)
        self.assertIn("输出前自检", system)
        self.assertIn("action_queue 必须从 position_reviews", system)
        self.assertIn("触发条件必须贴合该公司或资产的真实业务", system)
        self.assertIn("不得混用行业指标", system)
        self.assertIn("先给“结构化判断摘要”，再给“正式报告”", user)
        self.assertIn("等待用户确认”必须覆盖所有 position_reviews", user)
        self.assertNotIn("{{", user)


if __name__ == "__main__":
    unittest.main()
