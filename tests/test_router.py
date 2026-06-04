from __future__ import annotations

import unittest
from unittest.mock import patch

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

    def test_known_cash_anchor_symbol_routes_to_cash_anchor(self) -> None:
        with patch("src.master_router.extract_symbol", return_value="600900"), patch(
            "src.master_router.framework_for_known_holding",
            return_value="Cash_Anchor",
        ):
            state = route_intent(AgentState(user_input="满仓买入600900，直接给我执行建议"))

        self.assertEqual(state.framework_id, "Cash_Anchor")
        self.assertIn("本地持仓标的", state.route_reason or "")


if __name__ == "__main__":
    unittest.main()
