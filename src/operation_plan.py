"""Structured operation plans derived from action permissions.

Operation plans are account-facing memos, not trade instructions. They convert
permission results into stable actions such as watch, hold, add review, trim
review, or no action.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

from src.action_permission import build_action_permission_report


@dataclass(frozen=True)
class OperationPlan:
    ticker: str
    name: str
    framework_id: str
    market: str
    action: str
    final_status: str
    position_type: str
    permission_result: str
    rationale: list[str] = field(default_factory=list)
    execution_conditions: list[str] = field(default_factory=list)
    stop_review_conditions: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    user_approval_required: bool = False
    source_permission: dict[str, Any] = field(default_factory=dict)


def build_operation_framework_report(
    *,
    framework_id: str,
    market: str,
    workflow_type: str,
    tracked_symbols: list[dict[str, Any]],
    research_engine: dict[str, Any] | None = None,
    market_data: dict[str, Any] | None = None,
    data_gaps: list[str] | None = None,
    as_of: date | None = None,
) -> dict[str, Any]:
    """Build action permissions and operation plans for scheduled reviews."""

    permission_report = build_action_permission_report(
        framework_id=framework_id,
        market=market,
        workflow_type=workflow_type,
        tracked_symbols=tracked_symbols,
        research_engine=research_engine,
        market_data=market_data,
        data_gaps=data_gaps,
        as_of=as_of,
    )
    permissions = list(permission_report.get("permissions") or [])
    plans = [_plan_from_permission(item) for item in permissions if isinstance(item, dict)]
    return {
        "schema_version": 1,
        "engine": "operation_framework",
        "framework_id": framework_id,
        "market": market,
        "workflow_type": workflow_type,
        "as_of": (as_of or date.today()).isoformat(),
        "source_policy": "read_only; operation memo only; no trade execution",
        "action_permission": permission_report,
        "operation_plans": [asdict(item) for item in plans],
        "summary": _summary(plans),
    }


def format_operation_framework_report(report: dict[str, Any]) -> str:
    """Format an operation framework report for CLI/Feishu commands."""

    lines = [
        "Operation Framework 计划备忘录：",
        f"- framework：{report.get('framework_id')}",
        f"- market：{report.get('market')}",
        f"- 日期：{report.get('as_of')}",
        "- 写入策略：只读备忘录，不下单，不自动改仓位。",
    ]
    permission_summary = ((report.get("action_permission") or {}).get("summary") or {})
    lines.append(f"- 权限统计：{permission_summary.get('by_permission_result') or {}}")

    plans = list(report.get("operation_plans") or [])
    if plans:
        lines.extend(["", "Operation Plans："])
        for item in plans[:12]:
            lines.append(
                f"- {item.get('ticker')} {item.get('name')}："
                f"{item.get('permission_result')} -> {item.get('action')}，"
                f"{item.get('final_status')}"
            )
    approvals = [item for item in plans if item.get("user_approval_required")]
    if approvals:
        lines.extend(["", "需要人工确认："])
        for item in approvals[:8]:
            lines.append(f"- {item.get('ticker')}：{item.get('action')}")
    return "\n".join(lines)


def _plan_from_permission(permission: dict[str, Any]) -> OperationPlan:
    framework_id = str(permission.get("framework_id") or "")
    ticker = str(permission.get("ticker") or "").strip().upper()
    name = str(permission.get("name") or "").strip()
    market = str(permission.get("market") or "").strip().upper()
    permission_result = str(permission.get("permission_result") or "WATCH").upper()
    source_status = str(permission.get("source_status") or "")
    source_signal = permission.get("source_signal") if isinstance(permission.get("source_signal"), dict) else {}
    has_position = bool(source_signal.get("has_position")) or source_status == "holding"
    action = _action(framework_id, permission_result, source_status, has_position)
    final_status = _final_status(permission_result, action)
    rationale = list(permission.get("reasons") or [])
    constraints = list(permission.get("constraints") or [])
    blockers = list(permission.get("blockers") or [])
    risk_flags = list(permission.get("risk_flags") or [])
    execution_conditions = _execution_conditions(framework_id, action, source_signal, permission)
    stop_review_conditions = _stop_review_conditions(framework_id, action, source_signal, risk_flags)
    if blockers:
        constraints.extend(blockers)

    return OperationPlan(
        ticker=ticker,
        name=name,
        framework_id=framework_id,
        market=market,
        action=action,
        final_status=final_status,
        position_type=_position_type(framework_id, has_position, source_signal),
        permission_result=permission_result,
        rationale=_dedupe(rationale),
        execution_conditions=_dedupe(execution_conditions),
        stop_review_conditions=_dedupe(stop_review_conditions),
        constraints=_dedupe(constraints),
        user_approval_required=_approval_required(action, permission_result),
        source_permission=permission,
    )


def _action(framework_id: str, permission_result: str, source_status: str, has_position: bool) -> str:
    if permission_result == "REJECT":
        return "no_action"
    if permission_result == "WAIT":
        return "wait_for_price_or_event"
    if permission_result == "WATCH":
        if source_status in {"focus_watch", "buy_zone_candidate"}:
            return "focus_watch"
        if has_position:
            return "hold_with_research_required"
        return "watch"
    if permission_result == "WARN":
        if "trim" in source_status or "exit" in source_status:
            return "trim_review" if has_position else "no_action"
        if has_position:
            return "risk_review_hold"
        return "watch_only"
    if permission_result == "ALLOW":
        if framework_id == "Cash_Anchor":
            return "hold_review" if has_position else "watch"
        if "add" in source_status and has_position:
            return "add_plan_candidate"
        if "buy" in source_status and not has_position:
            return "buy_zone_candidate"
        return "hold_review" if has_position else "focus_watch"
    return "watch"


def _final_status(permission_result: str, action: str) -> str:
    if permission_result in {"REJECT", "WARN"} and action == "no_action":
        return "blocked"
    if action in {"add_plan_candidate", "buy_zone_candidate", "trim_review"}:
        return "wait_for_user_approval"
    if permission_result == "WAIT":
        return "waiting"
    return "memo_only"


def _execution_conditions(
    framework_id: str,
    action: str,
    source_signal: dict[str, Any],
    permission: dict[str, Any],
) -> list[str]:
    if framework_id == "Cash_Anchor":
        if action == "hold_review":
            return ["复核分红安全、仓位上限、估值纪律后继续持有。"]
        if action == "wait_for_price_or_event":
            return ["补齐行情、分红和仓位数据后再判断。"]
        return ["继续观察分红安全、估值和正式披露。"]

    validations = [str(item) for item in source_signal.get("next_validation") or []]
    if action == "add_plan_candidate":
        return [
            "只允许生成小比例、分批加仓计划。",
            "确认实时价格没有明显偏离估值纪律。",
            *validations[:3],
        ]
    if action == "buy_zone_candidate":
        return [
            "只允许进入买入观察区，不直接重仓。",
            "首次建仓计划不得超过目标仓位的 1/3。",
            *validations[:3],
        ]
    if action == "focus_watch":
        return ["进入重点观察，等待价格、财报或关键验证点。", *validations[:3]]
    if action == "wait_for_price_or_event":
        return ["等待估值回落、财报验证或风险事件消退。", *validations[:3]]
    if action in {"trim_review", "risk_review_hold"}:
        return ["复核风险事件、估值压力和原始买入逻辑是否失效。", *validations[:3]]
    return ["保持观察，不生成交易计划。", *validations[:3]]


def _stop_review_conditions(
    framework_id: str,
    action: str,
    source_signal: dict[str, Any],
    risk_flags: list[str],
) -> list[str]:
    if framework_id == "Cash_Anchor":
        return ["分红安全恶化、仓位超限、正式披露证伪或估值纪律失效时进入减仓/禁动审查。"]
    conditions = [str(item) for item in source_signal.get("evidence") or [] if "负向" in str(item) or "风险" in str(item)]
    if "thesis_weakened" in risk_flags:
        conditions.append("投研假设继续削弱或关键验证点失效。")
    if "valuation_extended" in risk_flags:
        conditions.append("估值继续扩张但基本面没有同步验证。")
    if not conditions:
        conditions.append("关键财报指标、竞争格局或现金流验证不达预期。")
    return conditions[:4]


def _position_type(framework_id: str, has_position: bool, source_signal: dict[str, Any]) -> str:
    if framework_id == "Cash_Anchor":
        return "cash_anchor_holding" if has_position else "cash_anchor_watch"
    asset_type = str(source_signal.get("asset_type") or "stock")
    if has_position:
        return f"growth_holding_{asset_type}"
    return f"growth_watch_{asset_type}"


def _approval_required(action: str, permission_result: str) -> bool:
    if action in {"add_plan_candidate", "buy_zone_candidate", "trim_review"}:
        return True
    return permission_result == "WARN"


def _summary(plans: list[OperationPlan]) -> dict[str, Any]:
    by_action: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for item in plans:
        by_action[item.action] = by_action.get(item.action, 0) + 1
        by_status[item.final_status] = by_status.get(item.final_status, 0) + 1
    return {
        "total": len(plans),
        "by_action": by_action,
        "by_final_status": by_status,
        "user_approval_required": sum(1 for item in plans if item.user_approval_required),
    }


def _dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        result.append(text)
        seen.add(text)
    return result
