"""私人投资管家的纯 Python 管道入口。"""

from __future__ import annotations

from uuid import uuid4

from src.auditor import audit_before_output, enforce_circuit_breaker
from src import communication_gate
from src.app_config import get_config
from src.budget_manager import trace_budget_start
from src.command_registry import handle_command
from src.context_logger import save_chat_session
from src.decision_record import save_decision_record
from src.error_classifier import classify_error
from src.master_router import route_intent
from src.output_contract import apply_output_contract
from src.skills import load_skill
from src.state import AgentState, DisclosureRecord, PipelineStatus
from src.session_lock import save_pending_action
from src.sub_agent import intake_precheck, stage_one_request_skills, stage_two_decide
from src.trace_logger import trace_state_event


def run_pipeline(user_input: str, chat_id: str = "cli") -> AgentState:
    """执行一次完整的用户交互管道。

    这里刻意不用 LangGraph 或其他状态机框架，而是通过显式控制流展示每个分支：
    路由、子 Agent 预检、弹回重试、渐进披露、子 Agent 决策、审计、放行。
    """

    state = AgentState(user_input=user_input, chat_id=chat_id)
    max_route_retries = get_config().router_max_route_retries()
    trace_state_event(state, "message_received", agent_role="master", metadata={"entrypoint": "pipeline"})
    trace_budget_start(
        trace_id=state.trace_id,
        chat_id=state.chat_id,
        framework_id=state.framework_id,
        workflow="natural_language_pipeline",
    )

    while True:
        # 1. Master 选择策略岛，并记录路由理由。
        state = route_intent(state)
        trace_state_event(
            state,
            "route_decision",
            agent_role="master_router",
            output_preview=state.route_reason,
            metadata={
                "route_attempts": state.route_attempts,
                "framework_id": state.framework_id,
                "bounce_reason": state.bounce_reason,
            },
        )
        communication_gate.send(
            chat_id,
            _route_user_message(state),
        )

        # 2. 被选中的子 Agent 可以在昂贵推理前拒绝接单。
        state = intake_precheck(state)

        if state.status == PipelineStatus.BOUNCED:
            if state.route_attempts >= max_route_retries:
                # 路由熔断：避免路由器和子 Agent 无限来回弹。
                state.append_error(
                    f"路由重试达到上限：{state.bounce_reason or 'unknown bounce reason'}"
                )
                trace_state_event(
                    state,
                    "route_bounce",
                    agent_role="worker",
                    status="failed",
                    output_preview=state.bounce_reason,
                    risk_flags=["route_bounced"],
                    metadata={"route_attempts": state.route_attempts},
                )
                communication_gate.send(chat_id, "\n".join(state.errors))
                _save_decision_state(state)
                save_chat_session(state)
                trace_state_event(state, "chat_session_saved", agent_role="context_logger")
                return state
            trace_state_event(
                state,
                "route_bounce",
                agent_role="worker",
                output_preview=state.bounce_reason,
                risk_flags=["route_bounced"],
                metadata={"route_attempts": state.route_attempts},
            )
            communication_gate.send(chat_id, f"当前框架不适用，重新路由：{state.bounce_reason}")
            state.reset_for_reroute()
            continue

        # 3. 子 Agent 在最终推理前申请最小必要数据。
        communication_gate.send(
            chat_id,
            _context_user_message(state),
        )
        state = stage_one_request_skills(state)
        trace_state_event(
            state,
            "skill_requested",
            agent_role="worker",
            output_preview=", ".join(item.skill_name for item in state.requested_skills),
            metadata={
                "requested_skills": [
                    {"skill_name": item.skill_name, "reason": item.reason, "arguments": item.arguments}
                    for item in state.requested_skills
                ]
            },
        )

        if state.status == PipelineStatus.NEEDS_DISCLOSURE:
            # 4. 只有主管道可以调用 Skill，并把结果披露回共享状态。
            for request in state.requested_skills:
                communication_gate.send(
                    chat_id,
                    _skill_user_message(request.skill_name),
                )
                try:
                    loaded_skill = load_skill(
                        request.skill_name,
                        request.arguments,
                        framework_id=state.framework_id,
                        agent_role="worker",
                    )
                except Exception as exc:
                    _handle_pipeline_error(state, chat_id, exc)
                    save_chat_session(state)
                    trace_state_event(
                        state,
                        "skill_disclosure_failed",
                        agent_role="main_pipeline",
                        status="error",
                        output_preview=state.final_answer,
                        risk_flags=["skill_disclosure_failed"],
                        error=str(exc),
                    )
                    trace_state_event(state, "chat_session_saved", agent_role="context_logger")
                    _save_decision_state(state)
                    return state
                state.disclosed_data.append(
                    DisclosureRecord(
                        skill_name=request.skill_name,
                        arguments=request.arguments,
                        payload=loaded_skill.to_payload(),
                    )
                )
                trace_state_event(
                    state,
                    "skill_disclosed",
                    agent_role="main_pipeline",
                    output_preview=request.skill_name,
                    metadata={
                        "skill_name": request.skill_name,
                        "arguments": request.arguments,
                        "payload_keys": sorted(loaded_skill.to_payload().keys()),
                    },
                )
            state.requested_skills.clear()
            state.status = PipelineStatus.RUNNING

        try:
            # 5. 子 Agent 生成决策草案，随后由 AOP 审计层拦截。
            state = stage_two_decide(state)
            state = apply_output_contract(state)
            trace_state_event(
                state,
                "draft_decision_created",
                agent_role="worker",
                output_preview=state.draft_decision,
                risk_flags=_decision_risk_flags(state),
                metadata={"output_contract": state.output_contract},
            )
            communication_gate.send(
                chat_id,
                "我把初步结论再过一遍风险，确认没硬伤就发给你。",
            )
            trace_state_event(state, "audit_started", agent_role="auditor")
            state = audit_before_output(state)
            trace_state_event(
                state,
                "audit_finished",
                agent_role="auditor",
                status=state.audit_signal or "unknown",
                output_preview=state.audit_log[-1].content if state.audit_log else "",
                risk_flags=_audit_risk_flags(state),
                metadata={"audit_persona": state.audit_persona, "audit_signal": state.audit_signal},
            )
            state = enforce_circuit_breaker(state)
            if state.status == PipelineStatus.AUDIT_REJECTED:
                trace_state_event(
                    state,
                    "circuit_breaker_triggered",
                    agent_role="main_pipeline",
                    status="rejected",
                    output_preview=state.final_answer,
                    risk_flags=["auditor_rejected"],
                )
            _send_terminal_result(chat_id, state)
            trace_state_event(
                state,
                "final_message_sent",
                agent_role="communication_gate",
                status=state.status.value,
                output_preview=state.final_answer,
            )
            _save_decision_state(state)
            save_chat_session(state)
            trace_state_event(state, "chat_session_saved", agent_role="context_logger")
            return state
        except Exception as exc:
            _handle_pipeline_error(state, chat_id, exc)
            _save_decision_state(state)
            save_chat_session(state)
            trace_state_event(
                state,
                "pipeline_failed",
                agent_role="main_pipeline",
                status="error",
                output_preview=state.final_answer,
                risk_flags=["pipeline_failed"],
                error=str(exc),
            )
            trace_state_event(state, "chat_session_saved", agent_role="context_logger")
            return state


def _send_terminal_result(chat_id: str, state: AgentState) -> None:
    """通过通讯网关发送最终报告或人工介入卡片。"""

    if state.status == PipelineStatus.AUDIT_REJECTED:
        action_id = str(uuid4())
        save_pending_action(
            chat_id=chat_id,
            action_id=action_id,
            framework_id=state.framework_id,
            reason=state.final_answer or "audit rejected",
        )
        communication_gate.send_card(
            chat_id,
            "审计未通过",
            state.final_answer or "审计发现风险，流程已暂停。",
            [
                {
                    "label": "继续执行",
                    "action": "force_execute",
                    "type": "danger",
                    "state_id": action_id,
                    "framework_id": state.framework_id,
                    "reason": (state.final_answer or "audit rejected")[:500],
                },
                {
                    "label": "放弃操作",
                    "action": "abandon_operation",
                    "type": "default",
                    "state_id": action_id,
                    "framework_id": state.framework_id,
                    "reason": (state.final_answer or "audit rejected")[:500],
                },
            ],
        )
        return

    communication_gate.send(chat_id, state.final_answer or "\n".join(state.errors))


def _route_user_message(state: AgentState) -> str:
    label = {
        "Cash_Anchor": "现金流和防守仓",
        "Growth_Engine": "成长仓",
    }.get(state.framework_id or "", state.framework_id or "当前问题")
    return f"我先按{label}来处理。"


def _context_user_message(state: AgentState) -> str:
    context = _framework_label(state.context_bundle_id or state.framework_id or "当前框架")
    return f"我会按 {context} 的规则看，同时只读这次需要的本地数据。"


def _skill_user_message(skill_name: str) -> str:
    messages = {
        "portfolio_snapshot": "我先读一下持仓、投入和分红账本。",
        "research_dossier": "我顺手看一下这个标的以前留下的研究档案。",
        "market-data": "我查一下只读行情，主要用于价格和纪律判断。",
        "trade_history": "我回看一下之前有没有相关判断记录。",
        "news-search": "我查一下近期外部信息，避免只看账本。",
        "announcement-search": "我查一下企业公告，只取财报和分配公告口径。",
    }
    return messages.get(skill_name, "我补一项必要数据。")


def _framework_label(value: str) -> str:
    labels = {
        "Cash_Anchor": "现金锚点",
        "Cash_Anchor_Core": "现金锚点",
        "CN_Dividend_Income": "境内红利现金流",
        "US_Income_Options": "美元收益",
        "Growth_Engine": "成长引擎",
        "Growth_Engine_Core": "成长引擎",
        "CN_Alpha_Growth": "境内成长",
        "US_Disruptive_Growth": "全球成长",
    }
    return labels.get(value, value)


def _handle_pipeline_error(state: AgentState, chat_id: str, exc: BaseException) -> None:
    """把模型/API 异常转换为可读失败状态，而不是让后台任务崩栈。"""

    classified = classify_error(exc)
    state.status = PipelineStatus.FAILED
    state.errors.append(f"{classified.kind.value}: {classified.raw_message}")
    state.final_answer = (
        f"流程已暂停：{classified.user_message}\n\n"
        f"错误分类：{classified.kind.value}\n"
        f"是否建议自动重试：{'是' if classified.retryable else '否'}"
    )
    communication_gate.send(chat_id, state.final_answer)


def _save_decision_state(state: AgentState) -> None:
    """Write Decision Record and trace the record path."""

    try:
        if state.draft_decision:
            state = apply_output_contract(state)
        path = save_decision_record(state)
    except Exception as exc:
        trace_state_event(
            state,
            "decision_record_failed",
            agent_role="decision_record",
            status="error",
            error=str(exc),
            risk_flags=["decision_record_failed"],
        )
        return
    trace_state_event(
        state,
        "decision_record_saved",
        agent_role="decision_record",
        metadata={"path": str(path)},
    )


def _decision_risk_flags(state: AgentState) -> list[str]:
    """根据草案和披露数据打低成本风险标签。"""

    flags: list[str] = []
    decision = state.draft_decision or ""
    if not state.disclosed_data and any(term in decision for term in ["买入", "加仓", "补仓", "建仓"]):
        flags.append("missing_disclosed_data")
    if any(term in decision for term in ["实时", "当前价格", "估值", "股息率"]) and not state.disclosed_data:
        flags.append("unsupported_price_claim")
    return flags


def _audit_risk_flags(state: AgentState) -> list[str]:
    """把审计结果转换为 trace 风险标签。"""

    flags: list[str] = []
    if state.audit_signal == "REJECT":
        flags.append("auditor_rejected")
    if state.audit_signal == "WARN":
        flags.append("auditor_warned")
    if state.audit_persona:
        flags.append(f"audit_persona:{state.audit_persona}")
    return flags


def main() -> None:
    """用于手动演练管道的命令行入口。"""

    user_input = input("User> ").strip()
    command_reply = handle_command(user_input, "cli")
    if command_reply is not None:
        print(command_reply)
        return
    run_pipeline(user_input, chat_id="cli")


if __name__ == "__main__":
    main()
