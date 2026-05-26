from __future__ import annotations

import unittest

from src.master_router import route_intent
from src.state import AgentState


class RouterTest(unittest.TestCase):
    def test_cash_anchor_route(self) -> None:
        state = route_intent(AgentState(user_input="红利持仓今年分红怎么看"))

        self.assertEqual(state.framework_id, "Cash_Anchor")
        self.assertEqual(state.route_attempts, 1)

    def test_cn_growth_route(self) -> None:
        state = route_intent(AgentState(user_input="A股半导体成长股跌破 MA120 怎么处理"))

        self.assertEqual(state.framework_id, "Growth_Engine")

    def test_us_growth_route(self) -> None:
        state = route_intent(AgentState(user_input="美股 AI SaaS 龙头估值怎么看"))

        self.assertEqual(state.framework_id, "Growth_Engine")


if __name__ == "__main__":
    unittest.main()
