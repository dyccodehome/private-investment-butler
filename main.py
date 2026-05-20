"""私人投资管家的纯 Python 管道入口。"""

from __future__ import annotations

from uuid import uuid4

from src.auditor import audit_before_output, enforce_circuit_breaker
from src import communication_gate
from src.command_registry import handle_command
from src.context_logger import save_chat_session
from src.error_classifier import classify_error
from src.master_router import route_intent
from src.skills import load_skill
from src.state import AgentState, DisclosureRecord, PipelineStatus
from src.session_lock import save_pending_action
from src.sub_agent import intake_precheck, stage_one_request_skills, stage_two_decide


MAX_ROUTE_RETRIES = 3


def run_pipeline(user_input: str, chat_id: str = "cli") -> AgentState:
    """执行一次完整的用户交互管道。

    这里刻意不用 LangGraph 或其他状态机框架，而是通过显式控制流展示每个分支：
    路由、子 Agent 预检、弹回重试、渐进披露、子 Agent 决策、审计、放行。
    """

    state = AgentState(user_input=user_input, chat_id=chat_id)

    while True:
        # 1. Master 选择策略岛，并记录路由理由。
        state = route_intent(state)
        communication_gate.send(
            chat_id,
            f"🔎 首席路由器判断：{state.route_reason} 目标框架：{state.framework_id}",
        )

        # 2. 被选中的子 Agent 可以在昂贵推理前拒绝接单。
        state = intake_precheck(state)

        if state.status == PipelineStatus.BOUNCED:
            if state.route_attempts >= MAX_ROUTE_RETRIES:
                # 路由熔断：避免路由器和子 Agent 无限来回弹。
                state.append_error(
                    f"路由重试达到上限：{state.bounce_reason or 'unknown bounce reason'}"
                )
                communication_gate.send(chat_id, "\n".join(state.errors))
                save_chat_session(state)
                return state
            communication_gate.send(chat_id, f"↩️ 子 Agent 拒单并弹回：{state.bounce_reason}")
            state.reset_for_reroute()
            continue

        # 3. 子 Agent 在最终推理前申请最小必要数据。
        communication_gate.send(
            chat_id,
            f"🔄 已锁定【{state.framework_id} / {state.context_bundle_id or '默认上下文'}】，"
            "子 Agent 正在申请按需披露的 Skill...",
        )
        state = stage_one_request_skills(state)

        if state.status == PipelineStatus.NEEDS_DISCLOSURE:
            # 4. 只有主管道可以调用 Skill，并把结果披露回共享状态。
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

        try:
            # 5. 子 Agent 生成决策草案，随后由 AOP 审计层拦截。
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
        except Exception as exc:
            _handle_pipeline_error(state, chat_id, exc)
            save_chat_session(state)
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
            "【极端风控官】已拦截该操作",
            state.final_answer or "审计触发强制拦截。",
            [
                {"label": "强行执行", "action": "force_execute", "type": "danger", "state_id": action_id},
                {"label": "放弃操作", "action": "abandon_operation", "type": "default", "state_id": action_id},
            ],
        )
        return

    communication_gate.send(chat_id, state.final_answer or "\n".join(state.errors))


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
