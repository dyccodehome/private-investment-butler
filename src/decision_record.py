"""Investment decision audit records.

Trace events describe technical flow. Decision records describe what the
investment runtime concluded, what evidence it disclosed, and how the audit
gate handled it.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.init import RUNTIME_DIR
from src.state import AgentState, PipelineStatus


DECISION_DIR = RUNTIME_DIR / "decisions"


@dataclass(frozen=True)
class DecisionRecord:
    """A compact, reviewable record of one terminal investment decision."""

    decision_id: str
    trace_id: str
    chat_id: str | None
    framework_id: str | None
    context_bundle_id: str | None
    decision_type: str
    user_input: str
    state_snapshot_refs: list[str] = field(default_factory=list)
    skill_disclosures: list[dict[str, Any]] = field(default_factory=list)
    draft_decision: str | None = None
    audit_persona: str | None = None
    audit_signal: str | None = None
    audit_summary: str = ""
    circuit_breaker: str = "not_triggered"
    final_answer: str | None = None
    allowed_actions: list[str] = field(default_factory=list)
    forbidden_actions: list[str] = field(default_factory=list)
    requires_human_approval: bool = False
    user_action: str | None = None
    status: str = ""
    errors: list[str] = field(default_factory=list)
    created_at: str = ""


def save_decision_record(state: AgentState) -> Path:
    """Append one terminal DecisionRecord to runtime/decisions."""

    now = datetime.now().replace(microsecond=0)
    record = build_decision_record(state, created_at=now.isoformat())
    DECISION_DIR.mkdir(parents=True, exist_ok=True)
    path = DECISION_DIR / f"{now:%Y-%m-%d}.jsonl"
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(asdict(record), ensure_ascii=False, default=str) + "\n")
    return path


def build_decision_record(state: AgentState, *, created_at: str | None = None) -> DecisionRecord:
    """Build a DecisionRecord from AgentState without writing it."""

    requires_human = state.status == PipelineStatus.AUDIT_REJECTED
    circuit_breaker = "triggered" if requires_human else "not_triggered"
    return DecisionRecord(
        decision_id=f"decision_{datetime.now():%Y%m%d}_{uuid4().hex[:10]}",
        trace_id=state.trace_id,
        chat_id=state.chat_id,
        framework_id=state.framework_id,
        context_bundle_id=state.context_bundle_id,
        decision_type=_decision_type(state),
        user_input=state.user_input,
        state_snapshot_refs=_state_snapshot_refs(state),
        skill_disclosures=[_compact_disclosure(item) for item in state.disclosed_data],
        draft_decision=state.draft_decision,
        audit_persona=state.audit_persona,
        audit_signal=state.audit_signal,
        audit_summary=_audit_summary(state),
        circuit_breaker=circuit_breaker,
        final_answer=state.final_answer,
        allowed_actions=[] if requires_human else ["send_final_answer"],
        forbidden_actions=["auto_execute_without_human_approval"] if requires_human else [],
        requires_human_approval=requires_human,
        user_action=state.user_action,
        status=state.status.value,
        errors=list(state.errors),
        created_at=created_at or datetime.now().replace(microsecond=0).isoformat(),
    )


def _decision_type(state: AgentState) -> str:
    if state.status == PipelineStatus.FAILED:
        return "pipeline_failure"
    if state.status == PipelineStatus.AUDIT_REJECTED:
        return "audit_rejected"
    if state.user_input.strip().startswith("/absorb"):
        return "knowledge_absorb"
    if state.framework_id == "Growth_Engine":
        return "growth_review"
    if state.framework_id == "Cash_Anchor":
        return "cash_anchor_review"
    return "general_pipeline"


def _state_snapshot_refs(state: AgentState) -> list[str]:
    refs: list[str] = []
    for item in state.disclosed_data:
        result = item.payload.get("result") if isinstance(item.payload, dict) else None
        if isinstance(result, dict):
            data = result.get("data") if isinstance(result.get("data"), dict) else {}
            for key in ("data_files", "path"):
                value = data.get(key)
                if isinstance(value, str):
                    refs.append(value)
                elif isinstance(value, dict):
                    refs.extend(str(path) for path in value.values())
    return sorted(set(refs))


def _compact_disclosure(item: Any) -> dict[str, Any]:
    result = item.payload.get("result") if isinstance(item.payload, dict) else None
    result_summary: dict[str, Any] = {}
    if isinstance(result, dict):
        data = result.get("data")
        result_summary = {
            "status": result.get("status"),
            "source": result.get("source"),
            "data_type": result.get("data_type"),
            "freshness": result.get("freshness"),
            "warnings": result.get("warnings") or [],
            "error": result.get("error") or "",
            "data_keys": sorted(data.keys()) if isinstance(data, dict) else [],
        }
    return {
        "skill_name": item.skill_name,
        "arguments": item.arguments,
        "result": result_summary,
    }


def _audit_summary(state: AgentState) -> str:
    if not state.audit_log:
        return ""
    latest = state.audit_log[-1]
    return str(latest.content or "")[:1000]
