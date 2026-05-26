"""飞书消息与卡片回调的共享运行时。

飞书 SDK 长连接入口复用这里的逻辑处理消息和卡片回调。
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import uuid4

from main import run_pipeline
from src import communication_gate
from src.command_registry import handle_command, help_text
from src.context_logger import save_user_action
from src.knowledge_absorber import (
    accept_patch_proposal,
    format_patch_proposal_for_user,
    mark_patch_proposal,
    parse_absorb_args,
    run_knowledge_absorption,
)
from src.session_lock import (
    acquire_processing,
    pop_pending_action,
    release_processing,
    save_pending_action,
)
from src.trace_logger import trace_event


_EXECUTOR = ThreadPoolExecutor(max_workers=4)


def handle_feishu_text_message(chat_id: str, text: str, *, async_run: bool = True) -> str:
    """处理一条飞书文本消息。"""

    text = _normalize_feishu_text(text)
    if not chat_id or not text:
        return "ignored unsupported event"

    if text.startswith("/absorb"):
        try:
            framework_id, source_text = parse_absorb_args(text.removeprefix("/absorb").strip())
        except ValueError as exc:
            communication_gate.send(chat_id, str(exc))
            return "absorb usage error"
        communication_gate.send(
            chat_id,
            "已收到新知识，正在分析是否需要修改框架。完成后会发送确认卡片。",
        )
        _submit_or_run(_run_absorb_background, async_run, chat_id, framework_id, source_text)
        return "absorb received"

    command_reply = handle_command(text, chat_id)
    if command_reply is not None:
        communication_gate.send(chat_id, command_reply)
        return "command handled"

    if text.startswith("/"):
        communication_gate.send(chat_id, "未知命令。可发送 /help 查看可用命令。\n\n" + help_text())
        return "unknown command"

    if not acquire_processing(chat_id):
        trace_event(
            trace_id=None,
            event_type="session_lock_rejected",
            chat_id=chat_id,
            agent_role="feishu_runtime",
            status="busy",
            input_preview=text,
            risk_flags=["session_busy"],
        )
        communication_gate.send(chat_id, "当前会话已有任务在处理中，请等待完成后再发送新请求。")
        return "busy"

    trace_event(
        trace_id=None,
        event_type="session_lock_acquired",
        chat_id=chat_id,
        agent_role="feishu_runtime",
        input_preview=text,
    )
    communication_gate.send(chat_id, "已收到请求，正在匹配投资框架。")
    _submit_or_run(_run_agent_background, async_run, chat_id, text)
    return "received"


def handle_feishu_card_callback(value: dict[str, Any]) -> str:
    """处理飞书卡片按钮回调。"""

    chat_id = str(value.get("chat_id") or "")
    action = str(value.get("action") or "")
    state_id = str(value.get("state_id") or "")

    pending = pop_pending_action(state_id)
    if not pending:
        if chat_id:
            communication_gate.send(chat_id, "该确认请求已过期或已处理。")
        return "no pending action"

    if action in {"accept_constitution_patch", "observe_constitution_patch", "reject_constitution_patch"}:
        trace_event(
            trace_id=pending.reason,
            event_type="human_callback_received",
            chat_id=pending.chat_id,
            framework_id=pending.framework_id,
            agent_role="human",
            input_preview=action,
            metadata={"state_id": state_id, "patch_id": pending.reason},
        )
        _handle_patch_callback(action, pending.chat_id, pending.framework_id, pending.reason)
    elif action == "force_execute":
        trace_event(
            trace_id=None,
            event_type="human_callback_received",
            chat_id=pending.chat_id,
            framework_id=pending.framework_id,
            agent_role="human",
            input_preview=action,
            risk_flags=["human_forced_execution"],
            metadata={"state_id": state_id},
        )
        reply = "已记录：用户选择在审计未通过的情况下继续执行。该操作会写入审计日志。"
        communication_gate.send(pending.chat_id, reply)
        save_user_action(
            chat_id=pending.chat_id,
            framework_id=pending.framework_id,
            user_action="user_clicked_force_execute",
            final_reply_to_user=reply,
            reason=pending.reason,
        )
    elif action == "abandon_operation":
        trace_event(
            trace_id=None,
            event_type="human_callback_received",
            chat_id=pending.chat_id,
            framework_id=pending.framework_id,
            agent_role="human",
            input_preview=action,
            metadata={"state_id": state_id},
        )
        reply = "已记录：用户接受审计意见，放弃本次操作。"
        communication_gate.send(pending.chat_id, reply)
        save_user_action(
            chat_id=pending.chat_id,
            framework_id=pending.framework_id,
            user_action="user_clicked_abandon_operation",
            final_reply_to_user=reply,
            reason=pending.reason,
        )
    else:
        communication_gate.send(pending.chat_id, f"未知确认动作：{action}")
    return "callback handled"


def _normalize_feishu_text(text: str) -> str:
    """清理飞书群聊里开头的 @ 机器人前缀，避免命令误入语义管道。"""

    text = text.strip()
    previous = None
    while previous != text:
        previous = text
        text = re.sub(r"^@\S+\s+", "", text).strip()
    return text


def _submit_or_run(function: Any, async_run: bool, *args: Any) -> None:
    if async_run:
        _EXECUTOR.submit(function, *args)
    else:
        function(*args)


def _run_agent_background(chat_id: str, text: str) -> None:
    """后台运行耗时 Agent 管道，并释放会话锁。"""

    try:
        run_pipeline(text, chat_id=chat_id)
    finally:
        release_processing(chat_id)


def _run_absorb_background(chat_id: str, framework_id: str, source_text: str) -> None:
    """后台运行宪法再造管道并推送审批卡片。"""

    proposal = run_knowledge_absorption(framework_id, source_text, chat_id=chat_id)
    text = format_patch_proposal_for_user(proposal)
    if proposal.status != "proposed":
        communication_gate.send(chat_id, text)
        return

    action_id = str(uuid4())
    save_pending_action(
        chat_id=chat_id,
        action_id=action_id,
        framework_id=framework_id,
        reason=proposal.patch_id,
    )
    communication_gate.send_card(
        chat_id,
        f"宪法进化提案 {proposal.patch_id}",
        text,
        [
            {"label": "同意并打入宪法", "action": "accept_constitution_patch", "type": "primary", "state_id": action_id},
            {"label": "进入观察池", "action": "observe_constitution_patch", "type": "default", "state_id": action_id},
            {"label": "拒绝修改", "action": "reject_constitution_patch", "type": "danger", "state_id": action_id},
        ],
    )


def _handle_patch_callback(action: str, chat_id: str, framework_id: str | None, patch_id: str) -> None:
    """处理宪法补丁审批按钮。"""

    if not framework_id:
        communication_gate.send(chat_id, "补丁审批失败：缺少 framework_id。")
        return
    try:
        if action == "accept_constitution_patch":
            archive_path = accept_patch_proposal(framework_id, patch_id)
            communication_gate.send(chat_id, f"已打入宪法并完成本地 Git commit：{patch_id}\n归档：{archive_path}")
        elif action == "observe_constitution_patch":
            archive_path = mark_patch_proposal(framework_id, patch_id, "observing")
            communication_gate.send(chat_id, f"已放入观察池：{patch_id}\n归档：{archive_path}")
        elif action == "reject_constitution_patch":
            archive_path = mark_patch_proposal(framework_id, patch_id, "rejected")
            communication_gate.send(chat_id, f"已拒绝该宪法补丁：{patch_id}\n归档：{archive_path}")
    except Exception as exc:
        communication_gate.send(chat_id, f"补丁审批执行失败：{exc}")
