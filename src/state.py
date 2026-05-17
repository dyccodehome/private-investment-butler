"""Global state container for the hand-rolled multi-agent pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


class PipelineStatus(str, Enum):
    """Lifecycle flags used by the pipeline loop to decide the next branch."""

    RUNNING = "running"
    NEEDS_DISCLOSURE = "needs_disclosure"
    BOUNCED = "bounced"
    AUDIT_REJECTED = "audit_rejected"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class SkillRequest:
    """A worker's explicit request for progressive data disclosure."""

    skill_name: str
    reason: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class DisclosureRecord:
    """Data disclosed by the pipeline after a skill call."""

    skill_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class DebateEntry:
    """Audit and debate log appended by the AOP auditor."""

    role: Literal["worker", "auditor", "master", "human"]
    content: str
    verdict: Literal["PASS", "WARN", "REJECT"] = "WARN"


@dataclass
class AgentState:
    """Single source of truth passed through every pipeline node.

    All pipeline nodes mutate and return this object instead of passing many
    scattered parameters. That keeps routing, skill requests, disclosed data,
    audit debate logs, and final output in one auditable record.
    """

    user_input: str
    chat_id: str | None = None
    framework_id: str | None = None
    route_reason: str | None = None
    route_attempts: int = 0
    bounce_back: bool = False
    bounce_reason: str | None = None
    requested_skills: list[SkillRequest] = field(default_factory=list)
    disclosed_data: list[DisclosureRecord] = field(default_factory=list)
    worker_notes: list[str] = field(default_factory=list)
    draft_decision: str | None = None
    audit_persona: str | None = None
    audit_log: list[DebateEntry] = field(default_factory=list)
    audit_signal: Literal["PASS", "WARN", "REJECT"] | None = None
    final_answer: str | None = None
    user_action: str | None = None
    status: PipelineStatus = PipelineStatus.RUNNING
    errors: list[str] = field(default_factory=list)

    def reset_for_reroute(self) -> None:
        """Prepare state for another router attempt after worker bounce-back.

        The rejection reason is intentionally retained in ``bounce_reason`` so
        the router can include it as penalty context on the next attempt.
        """

        # Clear only assignment fields; keep attempts and bounce_reason as trace.
        self.framework_id = None
        self.route_reason = None
        self.bounce_back = False
        self.status = PipelineStatus.RUNNING

    def append_error(self, message: str) -> None:
        """Record a terminal pipeline error and mark the lifecycle as failed."""

        self.errors.append(message)
        self.status = PipelineStatus.FAILED
