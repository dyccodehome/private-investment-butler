from __future__ import annotations

import json
import unittest

from src.state import AgentState, DisclosureRecord
from src.sub_agent import _compact_disclosed_data_for_prompt, load_strategy_context


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
        self.assertNotIn("raw market data should be omitted", compact)
        self.assertNotIn("full dividend event that should be omitted", compact)


if __name__ == "__main__":
    unittest.main()
