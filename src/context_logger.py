"""Conversation context logger.

Persists each completed interaction as JSON Lines under the selected strategy
island. This is the local-first "black box" fuel for weekly review agents.
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
    """Append one complete AgentState snapshot to strategy chat history.

    The file path is ``frameworks/{framework_id}/chat_history/YYYY-MM-DD.jsonl``.
    Each line is one interaction, making it cheap to stream or fully inject into
    a weekend review workflow.
    """

    framework_id = state.framework_id or "unrouted"
    history_dir = FRAMEWORKS_DIR / framework_id / "chat_history"
    history_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    log_path = history_dir / f"{now:%Y-%m-%d}.jsonl"
    record = _build_record(state, now)

    with log_path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    return log_path


def save_user_action(
    chat_id: str,
    framework_id: str | None,
    user_action: str,
    final_reply_to_user: str,
    reason: str = "",
) -> Path:
    """Append a Human-in-the-loop callback decision to chat history."""

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
    """Convert AgentState into a compact JSONL record."""

    return {
        "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        "chat_id": state.chat_id,
        "framework_id": state.framework_id,
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
    """Keep disclosed-data logs useful without storing full Skill prompts."""

    payload = dict(item.payload)
    payload.pop("instructions", None)
    return {
        "skill_name": item.skill_name,
        "arguments": item.arguments,
        "payload": payload,
    }
