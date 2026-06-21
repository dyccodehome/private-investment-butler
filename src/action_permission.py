"""Constitution-style action permission checks.

This module is the operation gate between research signals and account-facing
plans. It is deterministic, read-only, and deliberately conservative: it can
allow a plan to be drafted, but it never executes a trade.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any


VALID_PERMISSION_RESULTS = {"ALLOW", "WAIT", "WATCH", "WARN", "REJECT"}


@dataclass(frozen=True)
class ActionPermission:
    ticker: str
    name: str
    framework_id: str
    market: str
    permission_result: str
    permission_scope: str
    source_status: str
    reasons: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    requires_human_approval: bool = False
    source_signal: dict[str, Any] = field(default_factory=dict)


def build_action_permission_report(
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
    """Build a structured action-permission report for a scheduled context."""

    if framework_id == "Growth_Engine":
        permissions = _growth_permissions(
            market=market,
            research_engine=research_engine or {},
            data_gaps=data_gaps or [],
        )
    elif framework_id == "Cash_Anchor":
        permissions = _cash_permissions(
            market=market,
            tracked_symbols=tracked_symbols,
            market_data=market_data or {},
            data_gaps=data_gaps or [],
        )
    else:
        permissions = []

    return {
        "schema_version": 1,
        "engine": "action_permission",
        "framework_id": framework_id,
        "market": market,
        "workflow_type": workflow_type,
        "as_of": (as_of or date.today()).isoformat(),
        "source_policy": "read_only; permission only; no trade execution",
        "permissions": [asdict(item) for item in permissions],
        "summary": _summary(permissions),
    }


def _growth_permissions(
    *,
    market: str,
    research_engine: dict[str, Any],
    data_gaps: list[str],
) -> list[ActionPermission]:
    result: list[ActionPermission] = []
    signals = [item for item in research_engine.get("research_signals") or [] if isinstance(item, dict)]
    deep_queue_by_symbol = {
        str(item.get("ticker") or "").strip().upper(): item
        for item in research_engine.get("deep_research_queue") or []
        if isinstance(item, dict)
    }
    for signal in signals:
        ticker = str(signal.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        name = str(signal.get("name") or "").strip()
        has_position = bool(signal.get("has_position"))
        thesis = str(signal.get("thesis_impact") or "")
        valuation = str(signal.get("valuation_view") or "")
        evidence = str(signal.get("evidence_strength") or "")
        risk = str(signal.get("risk_level") or "")
        suggested_status = str(signal.get("suggested_status") or "")
        reasons = _growth_reasons(signal)
        constraints = [
            "任何买入、加仓、减仓或退出都只生成计划，不自动执行。",
            "执行前必须重新确认实时价格、仓位和财报/事件窗口。",
        ]
        blockers: list[str] = []
        risk_flags: list[str] = []

        if risk == "high":
            permission = "WARN" if has_position else "REJECT"
            scope = "risk_review" if has_position else "no_new_action"
            risk_flags.append("high_research_risk")
            blockers.append("Research Signal 风险等级为 high。")
        elif thesis == "weakened":
            permission = "WARN" if has_position else "REJECT"
            scope = "trim_or_exit_review" if has_position else "no_new_action"
            risk_flags.append("thesis_weakened")
            blockers.append("投研假设削弱，不能转成新增买入。")
        elif evidence == "low":
            permission = "WATCH" if not has_position else "WARN"
            scope = "research_required"
            risk_flags.append("low_evidence")
            blockers.append("证据强度不足。")
        elif valuation == "extended_above_ma120":
            permission = "WAIT"
            scope = "wait_for_price"
            risk_flags.append("valuation_extended")
            blockers.append("价格相对 MA120 明显扩张，等待估值或价格确认。")
        elif suggested_status in {"add_condition_review", "buy_zone_candidate"}:
            permission = "ALLOW"
            scope = "draft_limited_plan"
            constraints.append("首次或新增仓位只能生成分批计划，不能建议一次性重仓。")
        elif suggested_status in {"focus_watch", "hold_review"}:
            permission = "WATCH" if not has_position else "ALLOW"
            scope = "watch_or_hold"
        elif suggested_status in {"trim_review", "exit_review"}:
            permission = "WARN"
            scope = "trim_or_exit_review"
            risk_flags.append("exit_or_trim_review")
        else:
            permission = "WATCH"
            scope = "watch_only"

        queue_item = deep_queue_by_symbol.get(ticker)
        if queue_item:
            action = str(queue_item.get("suggested_action") or "")
            if action in {"create_dossier", "refresh_dossier", "risk_review", "update_thesis"}:
                constraints.append(f"先处理 Deep Research 队列：{action}。")
                risk_flags.append("deep_research_required")

        symbol_gaps = [gap for gap in data_gaps if ticker in gap]
        if symbol_gaps:
            constraints.extend(symbol_gaps[:2])
            risk_flags.append("data_gap")

        result.append(
            ActionPermission(
                ticker=ticker,
                name=name,
                framework_id="Growth_Engine",
                market=market,
                permission_result=_ensure_permission(permission),
                permission_scope=scope,
                source_status=suggested_status,
                reasons=reasons,
                constraints=_dedupe(constraints),
                blockers=_dedupe(blockers),
                risk_flags=_dedupe(risk_flags),
                requires_human_approval=permission in {"ALLOW", "WARN"},
                source_signal=signal,
            )
        )
    return result


def _cash_permissions(
    *,
    market: str,
    tracked_symbols: list[dict[str, Any]],
    market_data: dict[str, Any],
    data_gaps: list[str],
) -> list[ActionPermission]:
    permissions: list[ActionPermission] = []
    for item in tracked_symbols:
        ticker = str(item.get("symbol") or "").strip().upper()
        if not ticker:
            continue
        source = str(item.get("source") or "")
        name = str(item.get("name") or "").strip()
        symbol_market = str(item.get("market") or market or "").strip().upper() or market
        is_holding = source == "holding"
        symbol_market_data = market_data.get(ticker) or {}
        gaps = [gap for gap in data_gaps if ticker in gap or name and name in gap]
        risk_flags: list[str] = []
        blockers: list[str] = []
        constraints = [
            "Cash Anchor 只围绕分红安全、现金流、仓位上限和估值纪律生成建议。",
            "任何加仓、减仓或卖出都只生成计划，不自动执行。",
        ]
        if _market_data_missing(symbol_market_data):
            risk_flags.append("market_data_missing")
            constraints.append("行情缺失时不能确认估值、MA120 或加仓空间。")
        if gaps:
            risk_flags.append("data_gap")
            constraints.extend(gaps[:2])

        if is_holding and risk_flags:
            permission = "WARN"
            scope = "hold_with_data_gap"
            blockers.append("持仓关键数据存在缺口，先维持审查。")
        elif is_holding:
            permission = "ALLOW"
            scope = "hold_review"
        elif risk_flags:
            permission = "WAIT"
            scope = "watch_with_data_gap"
        else:
            permission = "WATCH"
            scope = "watch_only"

        permissions.append(
            ActionPermission(
                ticker=ticker,
                name=name,
                framework_id="Cash_Anchor",
                market=symbol_market,
                permission_result=_ensure_permission(permission),
                permission_scope=scope,
                source_status=source or "tracked",
                reasons=_cash_reasons(item, is_holding),
                constraints=_dedupe(constraints),
                blockers=_dedupe(blockers),
                risk_flags=_dedupe(risk_flags),
                requires_human_approval=permission in {"ALLOW", "WARN"},
                source_signal={},
            )
        )
    return permissions


def _growth_reasons(signal: dict[str, Any]) -> list[str]:
    return _dedupe(
        [
            f"投研假设：{signal.get('thesis_impact') or 'unknown'}。",
            f"估值视图：{signal.get('valuation_view') or 'unknown'}。",
            f"证据强度：{signal.get('evidence_strength') or 'unknown'}。",
            f"风险等级：{signal.get('risk_level') or 'unknown'}。",
        ]
    )


def _cash_reasons(item: dict[str, Any], is_holding: bool) -> list[str]:
    if is_holding:
        return ["标的是 Cash Anchor 持仓，优先生成持有、分红安全和仓位审查。"]
    return ["标的是 Cash Anchor 自选/观察标的，优先生成观察条件。"]


def _market_data_missing(payload: dict[str, Any]) -> bool:
    if not payload:
        return True
    status = str(payload.get("status") or "").lower()
    if status and status != "ok":
        return True
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    return not bool(data)


def _summary(permissions: list[ActionPermission]) -> dict[str, Any]:
    counts: dict[str, int] = {key: 0 for key in sorted(VALID_PERMISSION_RESULTS)}
    for item in permissions:
        counts[item.permission_result] = counts.get(item.permission_result, 0) + 1
    return {
        "total": len(permissions),
        "by_permission_result": counts,
        "requires_human_approval": sum(1 for item in permissions if item.requires_human_approval),
    }


def _ensure_permission(value: str) -> str:
    clean = str(value or "").strip().upper()
    if clean in VALID_PERMISSION_RESULTS:
        return clean
    return "WATCH"


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
