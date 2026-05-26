from __future__ import annotations

import unittest

from src.state import AgentState
from src.sub_agent import load_strategy_context


class SubAgentContextTest(unittest.TestCase):
    def test_growth_engine_loads_cn_sub_framework(self) -> None:
        state = AgentState(user_input="A股半导体成长股跌破 MA120 怎么处理", framework_id="Growth_Engine")

        context = load_strategy_context(state)

        self.assertEqual(state.context_bundle_id, "CN_Alpha_Growth")
        self.assertIn("frameworks/Growth_Engine/constitution.md", state.loaded_context_files)
        self.assertIn("frameworks/Growth_Engine/sub_frameworks/CN_Alpha_Growth.md", state.loaded_context_files)
        self.assertIn("中国成长引擎策略宪法", context)

    def test_growth_engine_loads_us_sub_framework(self) -> None:
        state = AgentState(user_input="美股 AI SaaS 龙头估值怎么看", framework_id="Growth_Engine")

        context = load_strategy_context(state)

        self.assertEqual(state.context_bundle_id, "US_Disruptive_Growth")
        self.assertIn("frameworks/Growth_Engine/sub_frameworks/US_Disruptive_Growth.md", state.loaded_context_files)
        self.assertIn("全球颠覆性成长策略宪法", context)


if __name__ == "__main__":
    unittest.main()
