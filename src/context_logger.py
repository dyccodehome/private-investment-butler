"""会话上下文记录器。

每次完整交互都会以 JSON Lines 形式固化到对应策略岛下。
这是本地优先的“会话黑匣子”，为周度复盘 Agent 提供底层燃料。
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from src.init import FRAMEWORKS_DIR
from src.state import AgentState, DebateEntry


def save_chat_session(state: AgentState) -> Path:
    """将一份完整 AgentState 快照追加到策略会话历史中。

    文件路径为 ``frameworks/{framework_id}/chat_history/YYYY-MM-DD.jsonl``。
    每一行是一轮交互，方便后续流式读取或完整注入周末复盘流程。
    """

    framework_id = state.framework_id or "unrouted"
    history_dir = FRAMEWORKS_DIR / framework_id / "chat_history"
    history_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    log_path = history_dir / f"{now:%Y-%m-%d}.jsonl"
    record = _build_record(state, now)

    with log_path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    _try_append_research_dossier_decision(state)
    return log_path


def save_user_action(
    chat_id: str,
    framework_id: str | None,
    user_action: str,
    final_reply_to_user: str,
    reason: str = "",
) -> Path:
    """将一次人工介入回调裁决追加到会话历史。"""

    state = AgentState(
        user_input="[interactive_callback]",
        chat_id=chat_id,
        framework_id=framework_id,
        final_answer=final_reply_to_user,
        user_action=user_action,
    )
    state.audit_log.append(
        DebateEntry(
            role="human",
            content=reason,
            verdict="WARN",
        )
    )
    return save_chat_session(state)


def _build_record(state: AgentState, timestamp: datetime) -> dict[str, Any]:
    """将 AgentState 转换为紧凑 JSONL 记录。"""

    return {
        "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        "chat_id": state.chat_id,
        "framework_id": state.framework_id,
        "context_bundle_id": state.context_bundle_id,
        "loaded_context_files": state.loaded_context_files,
        "route_reason": state.route_reason,
        "route_attempts": state.route_attempts,
        "user_query": state.user_input,
        "disclosed_data": [_compact_disclosure(item) for item in state.disclosed_data],
        "agent_proposal": state.draft_decision,
        "auditor_critique": [asdict(item) for item in state.audit_log],
        "audit_persona": state.audit_persona,
        "audit_signal": state.audit_signal,
        "final_reply_to_user": state.final_answer,
        "user_action": state.user_action,
        "worker_notes": state.worker_notes,
        "errors": state.errors,
        "status": state.status.value,
    }


def _compact_disclosure(item: Any) -> dict[str, Any]:
    """保留披露数据的可用信息，但不存储完整 Skill 提示词。"""

    payload = dict(item.payload)
    payload.pop("instructions", None)
    return {
        "skill_name": item.skill_name,
        "arguments": item.arguments,
        "payload": payload,
    }


def _try_append_research_dossier_decision(state: AgentState) -> None:
    """把相关交互追加到个股研究档案；失败不影响主会话归档。"""

    try:
        from src.research_dossier import append_decision_to_dossier

        append_decision_to_dossier(state)
    except Exception:
        return
