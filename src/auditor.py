"""AOP 风格的异步审计中间件。

审计模块与子 Agent 物理隔离为独立 LLM 调用；具体审计重点由业务场景动态注入
System Prompt。这样既保留模型层面的独立性，又避免为每个审计角色维护一套重复代码。
"""

from __future__ import annotations

import json

from src.data_quality import summarize_disclosures
from src.llm_client import LLMClient
from src.prompts import auditor_system_prompt, auditor_user_prompt
from src.research_dossier import extract_symbol
from src.skills import load_skill
from src.state import AgentState, DebateEntry, DisclosureRecord, PipelineStatus


DOOMER_PERSONA = "风险审计"
PURIST_PERSONA = "规则变更审计"
DEFAULT_PERSONA = "流程审计"

BUY_INTENT_TERMS = (
    "买入",
    "加仓",
    "补仓",
    "建仓",
    "增持",
    "抄底",
    "低吸",
    "配置",
    "buy",
    "add",
    "accumulate",
)

CONSTITUTION_PATCH_TERMS = (
    "/absorb",
    "absorb",
    "宪法",
    "框架",
    "补丁",
    "patch",
    "修改规则",
    "新增规则",
    "知识吸收",
)


def audit_before_output(state: AgentState) -> AgentState:
    """在用户看到结果前拦截每一次对外决策。

    审计模块放在子 Agent 外部。它会根据场景选择审计重点，
    独立加载反方证据 Skill，并在允许输出前把审计记录追加到全局状态。
    """

    persona = _select_persona(state)
    state.audit_persona = persona

    # 审计路径不信任子 Agent 的摘要，而是通过同一披露边界加载自己的反方证据 Skill。
    symbol = extract_symbol(state.user_input)
    adverse_arguments = {"symbol": symbol} if symbol else {"query": state.user_input[:120]}
    adverse_skill = load_skill(
        "news-search",
        adverse_arguments,
        framework_id=state.framework_id,
        agent_role="auditor",
    )
    state.disclosed_data.append(
        DisclosureRecord(
            skill_name="news-search",
            arguments=adverse_arguments,
            payload=adverse_skill.to_payload(),
        )
    )

    critique = _run_audit_llm(state, persona)
    verdict = _parse_audit_verdict(critique)

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
    """根据被拦截操作选择审计重点。"""

    text = f"{state.user_input}\n{state.draft_decision or ''}".lower()
    if any(term.lower() in text for term in CONSTITUTION_PATCH_TERMS):
        return PURIST_PERSONA
    if any(term.lower() in text for term in BUY_INTENT_TERMS):
        return DOOMER_PERSONA
    return DEFAULT_PERSONA


def _format_pass(state: AgentState) -> str:
    """构造审计未拒绝时面向用户的回复。"""

    answer = state.draft_decision or ""
    if state.audit_signal == "WARN":
        note = _audit_user_note(state)
        if note:
            return f"{answer}\n\n审计提醒：{note}"
    return answer


def _format_rejection(state: AgentState) -> str:
    """构造熔断触发时面向用户的回复。"""

    note = _audit_user_note(state) or "审计发现硬风险，我先把这次建议停住。"
    return f"我先把这次建议停住，等你确认。\n\n原因：{note}"


def _audit_user_note(state: AgentState) -> str:
    """Extract a short user-facing audit note without exposing the full audit log."""

    if not state.audit_log:
        return ""
    text = state.audit_log[-1].content.strip()
    lines = [
        line.strip(" -")
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("[")
    ]
    for marker in ("审计结论", "5. 审计结论"):
        for index, line in enumerate(lines):
            if marker in line and index + 1 < len(lines):
                return lines[index + 1][:160]
    return (lines[-1] if lines else text)[:160]


def _parse_audit_verdict(critique: str) -> str:
    """把审计输出第一行映射为管道可识别的信号。

    `[HUMAN_REVIEW]` 在工程语义上等同于暂停，因为自动化流程必须停止并等待人工确认。
    """

    upper = critique.upper()
    if "[REJECT]" in upper or "[HUMAN_REVIEW]" in upper:
        return "REJECT"
    if "[WARN]" in upper:
        return "WARN"
    return "PASS"


def _run_audit_llm(state: AgentState, persona: str) -> str:
    """让独立 LLM 审计子 Agent 决策。"""

    client = LLMClient.for_agent("auditor", state.framework_id)
    return client.complete(
        system_prompt=_build_system_prompt(persona),
        user_prompt=auditor_user_prompt(
            framework_id=state.framework_id,
            context_bundle_id=state.context_bundle_id,
            user_input=state.user_input,
            draft_decision=state.draft_decision,
            disclosed_data_summary=_summarize_disclosed_data(state),
        ),
        agent_role="auditor",
        call_site="auditor.audit_before_output",
        framework_id=state.framework_id,
        context_bundle_id=state.context_bundle_id,
        chat_id=state.chat_id,
        user_query=state.user_input,
        trace_id=state.trace_id,
    )


def _build_system_prompt(persona: str) -> str:
    """根据业务场景生成审计官的动态 System Prompt。"""

    return auditor_system_prompt(persona, risk_persona=DOOMER_PERSONA, purist_persona=PURIST_PERSONA)


def _summarize_disclosed_data(state: AgentState) -> str:
    """压缩已披露数据，避免审计 prompt 被原始 payload 撑爆。"""

    if not state.disclosed_data:
        return "无"

    rows: list[dict[str, object]] = []
    for item in state.disclosed_data[-5:]:
        rows.append(
            {
                "skill_name": item.skill_name,
                "arguments": item.arguments,
                "payload_keys": sorted(item.payload.keys()),
                "payload_preview": str(item.payload)[:600],
            }
        )
    return json.dumps(
        {
            "data_quality_summary": summarize_disclosures(state.disclosed_data),
            "output_contract": state.output_contract,
            "disclosures": rows,
        },
        ensure_ascii=False,
        indent=2,
    )
