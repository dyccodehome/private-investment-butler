"""AOP 风格的异步审计中间件。"""

from __future__ import annotations

from src.llm_client import LLMClient
from src.skills import load_skill
from src.state import AgentState, DebateEntry, DisclosureRecord, PipelineStatus


def audit_before_output(state: AgentState) -> AgentState:
    """在用户看到结果前拦截每一次对外决策。

    审计官刻意放在子 Agent 外部。它会选择反方人设，
    独立加载反方证据 Skill，并在允许输出前把辩论记录追加到全局状态。
    """

    persona = _select_persona(state)
    state.audit_persona = persona

    # 审计路径不信任子 Agent 的摘要，而是通过同一披露边界加载自己的反方证据 Skill。
    symbol = _extract_symbol_placeholder(state.user_input)
    adverse_skill = load_skill("news-search", {"symbol": symbol})
    state.disclosed_data.append(
        DisclosureRecord(
            skill_name="news-search",
            arguments={"symbol": symbol},
            payload=adverse_skill.to_payload(),
        )
    )

    critique = _run_audit_llm(state, persona)
    verdict = "REJECT" if "[REJECT]" in critique or "REJECT" in critique else "PASS"

    state.audit_log.append(
        DebateEntry(
            role="auditor",
            content=critique,
            verdict=verdict,
        )
    )
    state.audit_signal = verdict
    return state


def enforce_circuit_breaker(state: AgentState) -> AgentState:
    """把审计信号转换为最终输出或强制熔断。"""

    if state.audit_signal == "REJECT":
        # 人工介入边界：此时不输出自动化决策。
        state.status = PipelineStatus.AUDIT_REJECTED
        state.final_answer = _format_rejection(state)
        return state

    # 未被拒绝的决策会被格式化并发送给用户。
    state.status = PipelineStatus.COMPLETED
    state.final_answer = _format_pass(state)
    return state


def _select_persona(state: AgentState) -> str:
    """根据被拦截操作选择审计人设。"""

    text = state.user_input
    if "修改" in text or "宪法" in text or "框架" in text:
        return "逻辑洁癖者"
    if "复盘" in text or "总结" in text:
        return "过拟合纠察员"
    return "极端风控官"


def _format_pass(state: AgentState) -> str:
    """构造审计未拒绝时面向用户的回复。"""

    audit = "\n".join(f"- {item.content}" for item in state.audit_log)
    return f"{state.draft_decision}\n\n审计记录：\n{audit}"


def _format_rejection(state: AgentState) -> str:
    """构造熔断触发时面向用户的回复。"""

    audit = "\n".join(f"- [{item.verdict}] {item.content}" for item in state.audit_log)
    return "流程已熔断，等待 Human-in-the-loop 裁决。\n\n" + audit


def _extract_symbol_placeholder(user_input: str) -> str:
    """独立审计路径使用的临时标的提取器。"""

    return user_input.strip().split()[0] if user_input.strip() else "UNKNOWN"


def _run_audit_llm(state: AgentState, persona: str) -> str:
    """让独立 LLM 审计人设挑战子 Agent 决策。"""

    client = LLMClient.for_framework(state.framework_id)
    return client.complete(
        system_prompt=(
            f"你是{persona}，是私人投资管家的全链路审计官。"
            "你的职责是找出投资建议中的幻觉、顺从、过拟合和风控背离。"
            "如果必须阻断，请在第一行写 [REJECT]；否则第一行写 [ALLOW]。"
        ),
        user_prompt=(
            f"用户原话：{state.user_input}\n\n"
            f"子 Agent 草案：{state.draft_decision}\n\n"
            f"已披露数据数量：{len(state.disclosed_data)}\n"
            "请给出反方审计意见，必须简洁、可执行。"
        ),
        agent_role="auditor",
        call_site="auditor.audit_before_output",
        framework_id=state.framework_id,
        chat_id=state.chat_id,
        user_query=state.user_input,
    )
