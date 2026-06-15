"""Workflow token budget checks.

Token monitor records usage after each LLM call. Budget manager reads those
records and turns workflow budgets into trace-visible risk signals.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from src.app_config import get_config
from src.init import RUNTIME_DIR
from src.trace_logger import trace_event


TOKEN_USAGE_DIR = RUNTIME_DIR / "token_usage"


@dataclass(frozen=True)
class WorkflowBudget:
    workflow: str
    max_tokens: int
    warn_tokens: int


def workflow_budget(workflow: str) -> WorkflowBudget:
    """Return token budget for a workflow."""

    settings = get_config().budgets()
    default = dict(settings.get("default") or {})
    workflows = settings.get("workflows") or {}
    section = dict(workflows.get(workflow) or {})
    max_tokens = int(section.get("max_tokens") or default.get("max_tokens") or 0)
    warn_tokens = int(section.get("warn_tokens") or default.get("warn_tokens") or max_tokens)
    return WorkflowBudget(workflow=workflow, max_tokens=max_tokens, warn_tokens=warn_tokens)


def trace_budget_start(
    *,
    trace_id: str | None,
    chat_id: str | None,
    framework_id: str | None,
    workflow: str,
) -> None:
    """Record workflow budget at runtime start."""

    budget = workflow_budget(workflow)
    trace_event(
        trace_id=trace_id,
        event_type="budget_started",
        chat_id=chat_id,
        framework_id=framework_id,
        agent_role="budget_manager",
        metadata=asdict(budget),
    )


def record_budget_usage(
    *,
    trace_id: str | None,
    chat_id: str | None,
    framework_id: str | None,
    call_site: str,
    token_usage: dict[str, int],
) -> None:
    """Check cumulative tokens for this trace after an LLM call."""

    if not trace_id:
        return
    workflow = workflow_for_call_site(call_site)
    budget = workflow_budget(workflow)
    total_tokens = trace_token_total(trace_id)
    status = "success"
    risk_flags: list[str] = []
    if budget.max_tokens and total_tokens >= budget.max_tokens:
        status = "exceeded"
        risk_flags.append("budget_exceeded")
    elif budget.warn_tokens and total_tokens >= budget.warn_tokens:
        status = "warn"
        risk_flags.append("budget_warned")

    trace_event(
        trace_id=trace_id,
        event_type="budget_usage_checked",
        chat_id=chat_id,
        framework_id=framework_id,
        agent_role="budget_manager",
        status=status,
        token_usage={
            "latest_call_total_tokens": int(token_usage.get("total_tokens") or 0),
            "trace_total_tokens": total_tokens,
        },
        risk_flags=risk_flags,
        metadata=asdict(budget),
    )


def trace_token_total(trace_id: str, *, date: str | None = None) -> int:
    """Sum token usage for one trace_id from local token usage ledger."""

    target_date = date or datetime.now().strftime("%Y-%m-%d")
    path = TOKEN_USAGE_DIR / f"{target_date}.jsonl"
    if not path.exists():
        return 0
    total = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(record.get("trace_id") or "") != trace_id:
            continue
        total += int(record.get("total_tokens") or 0)
    return total


def workflow_for_call_site(call_site: str) -> str:
    """Map known call sites to workflow budget buckets."""

    if "growth_portfolio.review" in call_site:
        return "growth_daily_review"
    if "scheduled_review.run" in call_site:
        return "scheduled_review"
    if "knowledge_absorber.run_knowledge_absorption" in call_site:
        return "knowledge_absorb"
    if "absorb_discussion.run_absorb_discussion_turn" in call_site:
        return "absorb_discussion"
    return "natural_language_pipeline"
