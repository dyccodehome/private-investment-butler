"""Siloed worker executor with precheck and two-stage reasoning."""

from __future__ import annotations

from pathlib import Path

from src.init import FRAMEWORKS_DIR
from src.llm_client import LLMClient
from src.state import AgentState, PipelineStatus, SkillRequest


FRAMEWORK_KEYWORDS = {
    "Cash_Anchor": ["现金流", "红利", "股息", "分红", "低估值", "银行", "煤炭", "公用事业", "期权", "option", "covered call", "put", "call", "iv", "权利金"],
    "CN_Alpha_Growth": ["a股", "中国", "成长", "科技自立", "出海", "半导体", "新能源", "ma120", "产业升级", "本土"],
    "US_Disruptive_Growth": ["美股", "us", "ai", "saas", "生物科技", "英伟达", "微软", "全球", "颠覆", "tam"],
}


def load_constitution(framework_id: str) -> str:
    """Load only the selected framework's constitution.

    This enforces strategy isolation: a dividend worker never reads option or
    growth strategy rules while handling its own task.
    """

    path = FRAMEWORKS_DIR / framework_id / "constitution.md"
    return Path(path).read_text(encoding="utf-8")


def intake_precheck(state: AgentState) -> AgentState:
    """Let the selected worker decide whether it should accept the task.

    This is the bounce-back guard. The master router may make a wrong semantic
    assignment, so the worker performs a cheap local check before spending any
    LLM or data-fetching budget.
    """

    if not state.framework_id:
        state.append_error("Cannot precheck without framework_id.")
        return state

    text = state.user_input.lower()
    keywords = FRAMEWORK_KEYWORDS.get(state.framework_id, [])
    if keywords and not any(keyword in text for keyword in keywords):
        # Refuse the task and hand it back to the main pipeline for rerouting.
        state.bounce_back = True
        state.bounce_reason = (
            f"{state.framework_id} 预检拒单：用户问题与本策略宪法边界不匹配。"
        )
        state.status = PipelineStatus.BOUNCED
        return state

    # Loading constitution here proves the worker accepted the task and can now
    # reason inside its own isolated strategy space.
    constitution = load_constitution(state.framework_id)
    state.worker_notes.append(
        f"{state.framework_id} 接单。已加载宪法 {len(constitution)} 字。"
    )
    return state


def stage_one_request_skills(state: AgentState) -> AgentState:
    """Worker reads only constitution and user input, then asks for data.

    This implements progressive disclosure. The worker does not receive market,
    holding, or news data up front; it must explicitly request the minimum data
    needed for the next reasoning step.
    """

    if state.disclosed_data:
        # Data has already been disclosed, so this stage should not request it
        # again during the same pipeline pass.
        return state

    symbol = _extract_symbol_placeholder(state.user_input)
    state.requested_skills = [
        SkillRequest(
            skill_name="hithink-market-query",
            arguments={"symbol": symbol},
            reason="需要通过同花顺问财行情 Skill 获取实时市场事实。",
        ),
        SkillRequest(
            skill_name="trade_history",
            arguments={"symbol": symbol},
            reason="需要读取历史决策逻辑，避免重复犯错。",
        ),
    ]
    # Signal the main pipeline to pause worker reasoning and satisfy requests.
    state.status = PipelineStatus.NEEDS_DISCLOSURE
    return state


def stage_two_decide(state: AgentState) -> AgentState:
    """Worker combines disclosed data with constitution for if-then reasoning.

    The worker LLM receives only the selected constitution, user query, and
    data disclosed by the main pipeline. Other strategy islands remain hidden.
    """

    data_names = ", ".join(item.skill_name for item in state.disclosed_data) or "no data"
    constitution = load_constitution(state.framework_id or "")
    client = LLMClient.for_framework(state.framework_id)
    state.draft_decision = client.complete(
        system_prompt=(
            "你是私人投资管家的子 Agent。你只能依据当前策略宪法、用户原话、"
            "主管道披露的数据进行 If-Then 推演。不要编造未披露的实时数据。"
        ),
        user_prompt=(
            f"策略框架：{state.framework_id}\n"
            f"策略宪法：\n{constitution}\n\n"
            f"用户原话：{state.user_input}\n\n"
            f"已披露数据来源：{data_names}\n"
            f"已披露数据：{_compact_disclosed_data_for_prompt(state)}\n\n"
            "请输出：1. 核心判断；2. If-Then 执行纪律；3. 需要人工确认的风险点。"
        ),
        agent_role="worker",
        call_site="sub_agent.stage_two_decide",
        framework_id=state.framework_id,
        chat_id=state.chat_id,
        user_query=state.user_input,
    )
    state.worker_notes.append("子 Agent 完成第二阶段推演，等待审计切面拦截。")
    state.status = PipelineStatus.RUNNING
    return state


def _extract_symbol_placeholder(user_input: str) -> str:
    """Temporary symbol extractor until a real entity parser is introduced."""

    return user_input.strip().split()[0] if user_input.strip() else "UNKNOWN"


def _compact_disclosed_data_for_prompt(state: AgentState) -> str:
    """Pass only compact disclosed metadata to the model prompt."""

    compact = []
    for item in state.disclosed_data:
        compact.append(
            {
                "skill_name": item.skill_name,
                "arguments": item.arguments,
                "payload": item.payload,
            }
        )
    return str(compact)
