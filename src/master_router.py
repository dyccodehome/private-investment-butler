"""Semantic router with bounce-back aware retry context."""

from __future__ import annotations

from src.state import AgentState


FRAMEWORK_IDS = {
    "Cash_Anchor": "现金流防守、股息、分红、期权权利金、稳定流动性",
    "CN_Alpha_Growth": "A 股成长、科技自立、出海龙头、产业升级、MA120 趋势纪律",
    "US_Disruptive_Growth": "美股成长、AI、生物科技、SaaS、全球科技巨头、颠覆性创新",
}


def route_intent(state: AgentState) -> AgentState:
    """Map user intent to a unique framework id.

    This is intentionally transparent. A real deployment can replace the
    heuristic block with an LLM call while preserving the same state contract.
    The function mutates ``state.framework_id`` and appends a human-readable
    ``route_reason`` for later audit and debugging.
    """

    text = state.user_input.lower()
    # Every route call counts, including retries triggered by bounce-back.
    state.route_attempts += 1

    # The current version uses readable semantic hints. This can later become
    # an LLM classifier without changing downstream modules.
    if any(token in text for token in ["红利", "股息", "分红", "低估值", "银行", "煤炭", "公用事业", "期权", "option", "covered call", "put", "call", "iv", "权利金", "现金流"]):
        state.framework_id = "Cash_Anchor"
        state.route_reason = "识别到现金流防守、股息或期权权利金语义。"
    elif any(token in text for token in ["a股", "中国", "科技自立", "出海", "半导体", "新能源", "ma120", "本土", "产业升级"]):
        state.framework_id = "CN_Alpha_Growth"
        state.route_reason = "识别到中国成长股、本土阿尔法或 A 股趋势纪律语义。"
    elif any(token in text for token in ["美股", "us", "ai", "saas", "生物科技", "英伟达", "微软", "全球", "颠覆", "disruptive", "tam"]):
        state.framework_id = "US_Disruptive_Growth"
        state.route_reason = "识别到美股成长、全球创新或颠覆性成长语义。"
    else:
        state.framework_id = "Cash_Anchor"
        state.route_reason = "语义不充分，默认交给现金锚点框架预检。"

    # Feed the worker's rejection reason back into the next routing decision.
    if state.bounce_reason:
        state.route_reason += f" 上次拒单原因：{state.bounce_reason}"

    return state
