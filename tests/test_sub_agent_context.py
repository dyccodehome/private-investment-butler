from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from src.state import AgentState, DisclosureRecord, PipelineStatus
from src.sub_agent import _compact_disclosed_data_for_prompt, intake_precheck, load_strategy_context, stage_one_request_skills


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

    def test_worker_disclosure_prompt_compacts_portfolio_snapshot(self) -> None:
        state = AgentState(user_input="红利持仓今年怎么看", framework_id="Cash_Anchor")
        state.disclosed_data.append(
            DisclosureRecord(
                skill_name="portfolio_snapshot",
                arguments={"scope": "cash_anchor_dividend_retirement"},
                payload={
                    "result": {
                        "status": "ok",
                        "source": "local",
                        "data_type": "portfolio_snapshot",
                        "data": {
                            "as_of": "2026-06-04",
                            "summary": {"net_annual_dividend": 1234.56},
                            "dividend_analysis": {
                                "status": "has_gaps",
                                "forecast_from_holdings": {
                                    "net_annual_dividend_by_currency": [{"currency": "CNY", "amount": 1234.56}],
                                    "missing_annual_dividend_positions": [
                                        {"symbol": "QQQI.US", "name": "QQQI", "market": "US", "currency": "USD", "shares": 10}
                                    ],
                                },
                                "current_year_received": {
                                    "year": 2026,
                                    "event_count": 1,
                                    "events": [{"raw": "full dividend event that should be omitted"}],
                                },
                            },
                            "positions": [
                                {
                                    "symbol": "600900",
                                    "name": "长江电力",
                                    "market": "A股",
                                    "currency": "CNY",
                                    "shares": 300,
                                    "notes": "current_price=pending_quote",
                                }
                            ],
                            "position_limit_analysis": {
                                "status": "over_limit",
                                "scope": "A股红利池",
                                "positions": [
                                    {
                                        "symbol": "600900",
                                        "name": "长江电力",
                                        "market_value": 90000,
                                        "weight": 0.2,
                                        "limit_pct": 0.15,
                                        "can_add": False,
                                        "strict_max_add_market_value": 0,
                                        "add_guardrail": {
                                            "status": "over_limit",
                                            "can_add": False,
                                            "strict_max_add_market_value": 0,
                                            "binding_constraints": [
                                                {
                                                    "constraint_id": "single_position",
                                                    "label": "单票上限",
                                                    "status": "over_limit",
                                                    "max_add_market_value": 0,
                                                }
                                            ],
                                        },
                                    }
                                ],
                            },
                            "market_data": {"600900": "raw market data should be omitted" * 200},
                            "data_quality": {"status": "has_gaps"},
                        },
                        "freshness": {"as_of": "2026-06-04", "stale": False},
                        "warnings": [],
                        "error": "",
                    }
                },
            )
        )

        compact = _compact_disclosed_data_for_prompt(state)
        parsed = json.loads(compact)

        facts = parsed["disclosures"][0]["result"]["facts"]
        self.assertEqual(facts["summary"]["net_annual_dividend"], 1234.56)
        self.assertEqual(facts["positions"][0]["symbol"], "600900")
        self.assertEqual(
            facts["position_limit_analysis"]["positions"][0]["add_guardrail"]["status"],
            "over_limit",
        )
        self.assertNotIn("raw market data should be omitted", compact)
        self.assertNotIn("full dividend event that should be omitted", compact)

    def test_precheck_accepts_known_cash_anchor_symbol_without_keywords(self) -> None:
        state = AgentState(user_input="满仓买入600900，直接给我执行建议", framework_id="Cash_Anchor")

        with patch("src.sub_agent.symbol_in_framework", return_value=True), patch(
            "src.sub_agent.load_strategy_context",
            return_value="context",
        ):
            result = intake_precheck(state)

        self.assertFalse(result.bounce_back)
        self.assertEqual(result.status, PipelineStatus.RUNNING)

    def test_buy_intent_requests_portfolio_snapshot(self) -> None:
        state = AgentState(user_input="满仓买入600900，直接给我执行建议", framework_id="Cash_Anchor")

        result = stage_one_request_skills(state)

        self.assertEqual(result.status, PipelineStatus.NEEDS_DISCLOSURE)
        self.assertIn("portfolio_snapshot", [item.skill_name for item in result.requested_skills])


if __name__ == "__main__":
    unittest.main()
