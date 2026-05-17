"""Pure Python pipeline entry for the private investment butler."""

from __future__ import annotations

from uuid import uuid4

from src.auditor import audit_before_output, enforce_circuit_breaker
from src import communication_gate
from src.context_logger import save_chat_session
from src.master_router import route_intent
from src.skills import load_skill
from src.state import AgentState, DisclosureRecord, PipelineStatus
from src.session_lock import save_pending_action
from src.sub_agent import intake_precheck, stage_one_request_skills, stage_two_decide


MAX_ROUTE_RETRIES = 3


def run_pipeline(user_input: str, chat_id: str = "cli") -> AgentState:
    """Run one complete user interaction through the orchestration pipeline.

    The loop is intentionally hand-written instead of delegated to LangGraph or
    a state-machine framework. Each branch is visible: route, worker precheck,
    bounce-back retry, progressive disclosure, worker decision, audit, release.
    """

    state = AgentState(user_input=user_input, chat_id=chat_id)

    while True:
        # 1. Master picks a strategy island and records the routing rationale.
        state = route_intent(state)
        communication_gate.send(
            chat_id,
            f"🔎 首席路由器判断：{state.route_reason} 目标框架：{state.framework_id}",
        )

        # 2. The chosen worker may refuse the task before expensive reasoning.
        state = intake_precheck(state)

        if state.status == PipelineStatus.BOUNCED:
            if state.route_attempts >= MAX_ROUTE_RETRIES:
                # Retry fuse: avoid infinite router-worker ping-pong.
                state.append_error(
                    f"路由重试达到上限：{state.bounce_reason or 'unknown bounce reason'}"
                )
                communication_gate.send(chat_id, "\n".join(state.errors))
                save_chat_session(state)
                return state
            communication_gate.send(chat_id, f"↩️ 子 Agent 拒单并弹回：{state.bounce_reason}")
            state.reset_for_reroute()
            continue

        # 3. Worker asks for the minimum data it needs before final reasoning.
        communication_gate.send(
            chat_id,
            f"🔄 已锁定【{state.framework_id}】，子 Agent 正在申请按需披露的 Skill...",
        )
        state = stage_one_request_skills(state)

        if state.status == PipelineStatus.NEEDS_DISCLOSURE:
            # 4. Main pipeline is the only actor allowed to call skills and
            # disclose results back into the shared state.
            for request in state.requested_skills:
                communication_gate.send(
                    chat_id,
                    f"🧩 正在加载 Skill：{request.skill_name}。申请原因：{request.reason}",
                )
                loaded_skill = load_skill(request.skill_name, request.arguments)
                state.disclosed_data.append(
                    DisclosureRecord(
                        skill_name=request.skill_name,
                        arguments=request.arguments,
                        payload=loaded_skill.to_payload(),
                    )
                )
            state.requested_skills.clear()
            state.status = PipelineStatus.RUNNING

        # 5. Worker drafts a decision, then the AOP audit layer intercepts it.
        state = stage_two_decide(state)
        communication_gate.send(
            chat_id,
            "⚖️ 核心决策已生成，正在唤醒切面审计中间件进行反方逻辑对撞...",
        )
        state = audit_before_output(state)
        state = enforce_circuit_breaker(state)
        _send_terminal_result(chat_id, state)
        save_chat_session(state)
        return state


def _send_terminal_result(chat_id: str, state: AgentState) -> None:
    """Send final report or Human-in-the-loop card through the gate."""

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
            "【极端风控官】已拦截该操作",
            state.final_answer or "审计触发强制拦截。",
            [
                {"label": "强行执行", "action": "force_execute", "type": "danger", "state_id": action_id},
                {"label": "放弃操作", "action": "abandon_operation", "type": "default", "state_id": action_id},
            ],
        )
        return

    communication_gate.send(chat_id, state.final_answer or "\n".join(state.errors))


def main() -> None:
    """CLI entry point for manually exercising the pipeline."""

    user_input = input("User> ").strip()
    run_pipeline(user_input, chat_id="cli")


if __name__ == "__main__":
    main()
