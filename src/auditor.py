"""AOP-style asynchronous audit middleware."""

from __future__ import annotations

from src.llm_client import LLMClient
from src.skills import load_skill
from src.state import AgentState, DebateEntry, DisclosureRecord, PipelineStatus


def audit_before_output(state: AgentState) -> AgentState:
    """Intercept every outbound decision before the user sees it.

    The auditor is intentionally outside the worker. It selects a contrary
    persona, independently calls skills for adverse evidence, and appends its
    debate entry to the global state before output is allowed.
    """

    persona = _select_persona(state)
    state.audit_persona = persona

    # The audit path does not trust the worker's summary; it loads its own
    # adverse-evidence skill instructions through the same disclosure boundary.
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
    """Convert the audit signal into either final output or a hard stop."""

    if state.audit_signal == "REJECT":
        # Human-in-the-loop boundary: do not output an automated decision.
        state.status = PipelineStatus.AUDIT_REJECTED
        state.final_answer = _format_rejection(state)
        return state

    # Non-rejected decisions are formatted and released to the user.
    state.status = PipelineStatus.COMPLETED
    state.final_answer = _format_pass(state)
    return state


def _select_persona(state: AgentState) -> str:
    """Choose an audit persona based on the operation being intercepted."""

    text = state.user_input
    if "修改" in text or "宪法" in text or "框架" in text:
        return "逻辑洁癖者"
    if "复盘" in text or "总结" in text:
        return "过拟合纠察员"
    return "极端风控官"


def _format_pass(state: AgentState) -> str:
    """Build the user-facing response when audit does not reject."""

    audit = "\n".join(f"- {item.content}" for item in state.audit_log)
    return f"{state.draft_decision}\n\n审计记录：\n{audit}"


def _format_rejection(state: AgentState) -> str:
    """Build the user-facing response when the circuit breaker fires."""

    audit = "\n".join(f"- [{item.verdict}] {item.content}" for item in state.audit_log)
    return "流程已熔断，等待 Human-in-the-loop 裁决。\n\n" + audit


def _extract_symbol_placeholder(user_input: str) -> str:
    """Temporary symbol extractor used by the independent auditor path."""

    return user_input.strip().split()[0] if user_input.strip() else "UNKNOWN"


def _run_audit_llm(state: AgentState, persona: str) -> str:
    """Ask an independent LLM persona to challenge the worker decision."""

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
