"""Scheduled investment review workflows.

The scheduler should not know strategy details. This module builds bounded,
auditable contexts for pre-market plans, post-close reviews, and weekly
reviews, then stores every terminal result under the owning strategy island.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.init import FRAMEWORKS_DIR
from src.llm_client import LLMClient
from src.prompts import scheduled_review_system_prompt, scheduled_review_user_prompt
from src.trace_logger import trace_event


DAILY_REPORT_DIR = "daily_reviews"
WEEKLY_REPORT_DIR = "weekly_reviews"
MAX_CONTEXT_SYMBOLS = 12
MAX_INTEL_ITEMS_PER_SOURCE = 3
VALID_FRAMEWORKS = {"Cash_Anchor", "Growth_Engine"}
VALID_MARKETS = {"CN", "US", "ALL"}
VALID_WORKFLOW_TYPES = {"premarket", "close", "weekly"}

FRAMEWORK_LABELS = {
    "Cash_Anchor": "Cash Anchor",
    "Growth_Engine": "Growth Engine",
}
WORKFLOW_LABELS = {
    "premarket": "开盘前计划",
    "close": "收盘后复盘",
    "weekly": "周复盘",
}
CONTEXT_BUNDLE_BY_FRAMEWORK_MARKET = {
    ("Cash_Anchor", "CN"): "CN_Dividend_Income",
    ("Cash_Anchor", "US"): "US_Income_Options",
    ("Growth_Engine", "US"): "US_Disruptive_Growth",
}


@dataclass(frozen=True)
class TrackedSymbol:
    symbol: str
    name: str
    market: str
    source: str
    priority: str = ""
    notes: str = ""


def run_scheduled_premarket_review(
    framework_id: str,
    market: str,
    *,
    chat_id: str | None = None,
    as_of: date | None = None,
) -> str:
    """Run one pre-market plan workflow."""

    return run_scheduled_daily_review(
        framework_id=framework_id,
        market=market,
        workflow_type="premarket",
        chat_id=chat_id,
        as_of=as_of,
    )


def run_scheduled_close_review(
    framework_id: str,
    market: str,
    *,
    chat_id: str | None = None,
    as_of: date | None = None,
) -> str:
    """Run one post-close review workflow."""

    return run_scheduled_daily_review(
        framework_id=framework_id,
        market=market,
        workflow_type="close",
        chat_id=chat_id,
        as_of=as_of,
    )


def run_scheduled_daily_review(
    *,
    framework_id: str,
    market: str,
    workflow_type: str,
    chat_id: str | None = None,
    as_of: date | None = None,
) -> str:
    """Run one daily scheduled workflow and persist its result."""

    clean_framework = _validate_framework(framework_id)
    clean_market = _validate_market(market, allow_all=False)
    _validate_framework_market(clean_framework, clean_market)
    clean_workflow = _validate_workflow_type(workflow_type, allow_weekly=False)
    target_date = as_of or date.today()
    trace_id = f"trace_scheduled_{uuid4().hex[:12]}"
    context_bundle_id = _context_bundle(clean_framework, clean_market)

    trace_event(
        trace_id=trace_id,
        event_type="scheduled_review_started",
        chat_id=chat_id,
        framework_id=clean_framework,
        agent_role="scheduler",
        input_preview=f"{clean_workflow}:{clean_framework}:{clean_market}:{target_date.isoformat()}",
        metadata={"workflow_type": clean_workflow, "market": clean_market},
    )
    _trace_budget_start(trace_id=trace_id, chat_id=chat_id, framework_id=clean_framework)

    context = build_daily_review_context(
        framework_id=clean_framework,
        market=clean_market,
        workflow_type=clean_workflow,
        as_of=target_date,
    )
    if not context["tracked_symbols"]:
        result = _empty_daily_result(clean_framework, clean_market, clean_workflow, target_date, context)
        record, path = save_scheduled_review(
            framework_id=clean_framework,
            market=clean_market,
            workflow_type=clean_workflow,
            review_date=target_date,
            trace_id=trace_id,
            context_bundle_id=context_bundle_id,
            context=context,
            result=result,
            status="skipped",
            chat_id=chat_id,
        )
        _archive_scheduled_terminal_record(record, path, chat_id=chat_id)
        _trace_review_finished(trace_id, chat_id, clean_framework, record, path)
        return _format_scheduled_result(record, path)

    result = _run_scheduled_review_llm(
        framework_id=clean_framework,
        market=clean_market,
        workflow_type=clean_workflow,
        review_date=target_date,
        context_bundle_id=context_bundle_id,
        context=context,
        chat_id=chat_id,
        trace_id=trace_id,
    )
    record, path = save_scheduled_review(
        framework_id=clean_framework,
        market=clean_market,
        workflow_type=clean_workflow,
        review_date=target_date,
        trace_id=trace_id,
        context_bundle_id=context_bundle_id,
        context=context,
        result=result,
        status="ok",
        chat_id=chat_id,
    )
    _archive_scheduled_terminal_record(record, path, chat_id=chat_id)
    _trace_review_finished(trace_id, chat_id, clean_framework, record, path)
    return _format_scheduled_result(record, path)


def run_scheduled_weekly_review(
    framework_id: str,
    *,
    chat_id: str | None = None,
    as_of: date | None = None,
) -> str:
    """Run one weekly review for a single strategy island."""

    clean_framework = _validate_framework(framework_id)
    target_date = as_of or date.today()
    trace_id = f"trace_scheduled_{uuid4().hex[:12]}"
    context_bundle_id = clean_framework

    trace_event(
        trace_id=trace_id,
        event_type="scheduled_review_started",
        chat_id=chat_id,
        framework_id=clean_framework,
        agent_role="scheduler",
        input_preview=f"weekly:{clean_framework}:{target_date.isoformat()}",
        metadata={"workflow_type": "weekly", "market": "ALL"},
    )
    _trace_budget_start(trace_id=trace_id, chat_id=chat_id, framework_id=clean_framework)

    context = build_weekly_review_context(framework_id=clean_framework, as_of=target_date)
    if not context["daily_records"]:
        result = _empty_weekly_result(clean_framework, target_date, context)
        record, path = save_scheduled_review(
            framework_id=clean_framework,
            market="ALL",
            workflow_type="weekly",
            review_date=target_date,
            trace_id=trace_id,
            context_bundle_id=context_bundle_id,
            context=context,
            result=result,
            status="skipped",
            chat_id=chat_id,
        )
        _archive_scheduled_terminal_record(record, path, chat_id=chat_id)
        _trace_review_finished(trace_id, chat_id, clean_framework, record, path)
        return _format_scheduled_result(record, path)

    result = _run_scheduled_review_llm(
        framework_id=clean_framework,
        market="ALL",
        workflow_type="weekly",
        review_date=target_date,
        context_bundle_id=context_bundle_id,
        context=context,
        chat_id=chat_id,
        trace_id=trace_id,
    )
    record, path = save_scheduled_review(
        framework_id=clean_framework,
        market="ALL",
        workflow_type="weekly",
        review_date=target_date,
        trace_id=trace_id,
        context_bundle_id=context_bundle_id,
        context=context,
        result=result,
        status="ok",
        chat_id=chat_id,
    )
    _archive_scheduled_terminal_record(record, path, chat_id=chat_id)
    _trace_review_finished(trace_id, chat_id, clean_framework, record, path)
    return _format_scheduled_result(record, path)


def build_daily_review_context(
    *,
    framework_id: str,
    market: str,
    workflow_type: str,
    as_of: date | None = None,
) -> dict[str, Any]:
    """Build the bounded context injected into one daily scheduled review."""

    clean_framework = _validate_framework(framework_id)
    clean_market = _validate_market(market, allow_all=False)
    _validate_framework_market(clean_framework, clean_market)
    clean_workflow = _validate_workflow_type(workflow_type, allow_weekly=False)
    target_date = as_of or date.today()
    snapshot = _build_framework_snapshot(clean_framework, clean_market, target_date)
    tracked = _tracked_symbols_from_snapshot(clean_framework, snapshot)
    previous_close = read_recent_daily_reviews(
        clean_framework,
        market=clean_market,
        workflow_type="close",
        before=target_date,
        limit=1,
    )
    same_day_premarket = []
    if clean_workflow == "close":
        same_day_premarket = read_daily_reviews_on(
            clean_framework,
            target_date,
            market=clean_market,
            workflow_type="premarket",
        )
    latest_weekly = read_recent_weekly_reviews(clean_framework, before=target_date + timedelta(days=1), limit=1)
    limited_tracked = tracked[:MAX_CONTEXT_SYMBOLS]
    market_data = _collect_market_data(limited_tracked)
    intel = _collect_symbol_intel(limited_tracked)
    dossiers = _collect_research_dossier_summaries(clean_framework, limited_tracked)

    return {
        "schema_version": 1,
        "review_date": target_date.isoformat(),
        "framework_id": clean_framework,
        "framework_label": FRAMEWORK_LABELS[clean_framework],
        "market": clean_market,
        "workflow_type": clean_workflow,
        "workflow_label": WORKFLOW_LABELS[clean_workflow],
        "context_bundle_id": _context_bundle(clean_framework, clean_market),
        "strategy_context": _load_strategy_context(clean_framework, clean_market),
        "snapshot": snapshot,
        "tracked_symbols": [asdict(item) for item in tracked],
        "context_symbol_limit": MAX_CONTEXT_SYMBOLS,
        "market_data": market_data,
        "symbol_intel": intel,
        "research_dossiers": dossiers,
        "history": {
            "previous_close": _compact_records(previous_close, include_context=False),
            "same_day_premarket": _compact_records(same_day_premarket, include_context=False),
            "latest_weekly_plan": _compact_records(latest_weekly, include_context=False),
        },
        "optional_data_notes": _research_dossier_notes(dossiers),
        "instructions": _workflow_instructions(clean_framework, clean_market, clean_workflow),
        "data_gaps": _daily_data_gaps(snapshot, tracked, market_data, intel, dossiers),
    }


def build_weekly_review_context(*, framework_id: str, as_of: date | None = None) -> dict[str, Any]:
    """Build context for one strategy-island weekly review."""

    clean_framework = _validate_framework(framework_id)
    target_date = as_of or date.today()
    start_date = target_date - timedelta(days=6)
    daily_records = read_daily_reviews_between(clean_framework, start_date, target_date)
    us_snapshot = _build_framework_snapshot(clean_framework, "US", target_date)
    snapshots = {"US": us_snapshot}
    tracked_source = _tracked_symbols_from_snapshot(clean_framework, us_snapshot)
    if clean_framework == "Cash_Anchor":
        cn_snapshot = _build_framework_snapshot(clean_framework, "CN", target_date)
        snapshots = {"CN": cn_snapshot, "US": us_snapshot}
        tracked_source = _tracked_symbols_from_snapshot(clean_framework, cn_snapshot) + tracked_source
    tracked = _dedupe_tracked(tracked_source)
    limited_tracked = tracked[:MAX_CONTEXT_SYMBOLS]
    intel = _collect_symbol_intel(limited_tracked)
    dossiers = _collect_research_dossier_summaries(clean_framework, limited_tracked)

    return {
        "schema_version": 1,
        "review_date": target_date.isoformat(),
        "week_start": start_date.isoformat(),
        "week_end": target_date.isoformat(),
        "framework_id": clean_framework,
        "framework_label": FRAMEWORK_LABELS[clean_framework],
        "market": "ALL",
        "workflow_type": "weekly",
        "workflow_label": WORKFLOW_LABELS["weekly"],
        "context_bundle_id": clean_framework,
        "strategy_context": _load_strategy_context(clean_framework, "ALL"),
        "snapshots": snapshots,
        "tracked_symbols": [asdict(item) for item in tracked],
        "context_symbol_limit": MAX_CONTEXT_SYMBOLS,
        "symbol_intel": intel,
        "research_dossiers": dossiers,
        "daily_records": _compact_records(daily_records, include_context=False),
        "record_counts": _record_counts(daily_records),
        "optional_data_notes": _research_dossier_notes(dossiers),
        "instructions": _workflow_instructions(clean_framework, "ALL", "weekly"),
        "data_gaps": _weekly_data_gaps(daily_records, tracked, intel, dossiers, framework_id=clean_framework),
    }


def save_scheduled_review(
    *,
    framework_id: str,
    market: str,
    workflow_type: str,
    review_date: date,
    trace_id: str,
    context_bundle_id: str,
    context: dict[str, Any],
    result: str,
    status: str,
    chat_id: str | None,
    error: str = "",
) -> tuple[dict[str, Any], Path]:
    """Append one scheduled review record to its strategy-island report folder."""

    report_dir = _report_dir(framework_id, workflow_type)
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"{review_date.isoformat()}.jsonl"
    created_at = datetime.now().replace(microsecond=0).isoformat()
    record = {
        "schema_version": 1,
        "record_id": f"scheduled_{datetime.now():%Y%m%d}_{uuid4().hex[:10]}",
        "created_at": created_at,
        "review_date": review_date.isoformat(),
        "trace_id": trace_id,
        "chat_id": chat_id,
        "framework_id": framework_id,
        "framework_label": FRAMEWORK_LABELS.get(framework_id, framework_id),
        "context_bundle_id": context_bundle_id,
        "market": market,
        "workflow_type": workflow_type,
        "workflow_label": WORKFLOW_LABELS.get(workflow_type, workflow_type),
        "status": status,
        "error": error,
        "tracked_symbol_count": len(context.get("tracked_symbols") or []),
        "context": context,
        "result": result,
    }
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    return record, path


def read_recent_daily_reviews(
    framework_id: str,
    *,
    market: str | None = None,
    workflow_type: str | None = None,
    before: date | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Read recent daily records, newest first."""

    records = [
        record
        for record in _iter_records(framework_id, DAILY_REPORT_DIR)
        if _matches_record(record, market=market, workflow_type=workflow_type)
        and _record_date(record) is not None
        and (before is None or _record_date(record) < before)
    ]
    records.sort(key=lambda row: (str(row.get("review_date") or ""), str(row.get("created_at") or "")), reverse=True)
    return records[:limit]


def read_daily_reviews_on(
    framework_id: str,
    target_date: date,
    *,
    market: str | None = None,
    workflow_type: str | None = None,
) -> list[dict[str, Any]]:
    records = [
        record
        for record in _iter_records(framework_id, DAILY_REPORT_DIR)
        if _matches_record(record, market=market, workflow_type=workflow_type)
        and _record_date(record) == target_date
    ]
    records.sort(key=lambda row: str(row.get("created_at") or ""))
    return records


def read_daily_reviews_between(framework_id: str, start_date: date, end_date: date) -> list[dict[str, Any]]:
    """Read daily review records in chronological order."""

    records = [
        record
        for record in _iter_records(framework_id, DAILY_REPORT_DIR)
        if _record_date(record) is not None and start_date <= _record_date(record) <= end_date
    ]
    records.sort(key=lambda row: (str(row.get("review_date") or ""), str(row.get("created_at") or "")))
    return records


def read_recent_weekly_reviews(
    framework_id: str,
    *,
    before: date | None = None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    records = [
        record
        for record in _iter_records(framework_id, WEEKLY_REPORT_DIR)
        if _record_date(record) is not None and (before is None or _record_date(record) < before)
    ]
    records.sort(key=lambda row: (str(row.get("review_date") or ""), str(row.get("created_at") or "")), reverse=True)
    return records[:limit]


def _run_scheduled_review_llm(
    *,
    framework_id: str,
    market: str,
    workflow_type: str,
    review_date: date,
    context_bundle_id: str,
    context: dict[str, Any],
    chat_id: str | None,
    trace_id: str,
) -> str:
    client = LLMClient.for_framework(framework_id)
    return client.complete(
        system_prompt=scheduled_review_system_prompt(),
        user_prompt=scheduled_review_user_prompt(
            framework_id=framework_id,
            market=market,
            workflow_type=workflow_type,
            review_date=review_date.isoformat(),
            context_json=json.dumps(context, ensure_ascii=False, indent=2, default=str),
        ),
        agent_role="scheduled_reviewer",
        call_site="scheduled_review.run",
        framework_id=framework_id,
        context_bundle_id=context_bundle_id,
        chat_id=chat_id,
        user_query=f"scheduled_review:{workflow_type}:{framework_id}:{market}:{review_date.isoformat()}",
        trace_id=trace_id,
    )


def _build_framework_snapshot(framework_id: str, market: str, as_of: date) -> dict[str, Any]:
    if framework_id == "Growth_Engine":
        from src.growth_portfolio import build_growth_snapshot

        clean_market = _validate_market(market, allow_all=True)
        _validate_framework_market(framework_id, clean_market)
        snapshot = build_growth_snapshot(market="US")
        if clean_market in {"US", "ALL"}:
            snapshot = _attach_longbridge_growth_universe(snapshot)
        return snapshot
    if framework_id == "Cash_Anchor":
        from src.cash_anchor_watchlist import build_cash_watchlist_snapshot
        from src.portfolio_ledger import build_portfolio_snapshot

        snapshot = build_portfolio_snapshot(as_of=as_of)
        clean_market = _validate_market(market, allow_all=True)
        positions = list(snapshot.get("positions") or [])
        filtered_positions = [
            item for item in positions if clean_market == "ALL" or _normalize_market_value(item.get("market"), item.get("symbol")) == clean_market
        ]
        watchlist = build_cash_watchlist_snapshot(market=None if clean_market == "ALL" else clean_market)
        result = {
            **snapshot,
            "market_filter": clean_market,
            "portfolio_summary_all_markets": snapshot.get("summary") or {},
            "positions": filtered_positions,
            "summary": {
                **dict(snapshot.get("summary") or {}),
                "filtered_holding_count": len(filtered_positions),
                "filtered_watchlist_count": len(watchlist.get("watchlist") or []),
            },
            "watchlist": watchlist.get("watchlist") or [],
            "watchlist_snapshot": watchlist,
        }
        if clean_market in {"US", "ALL"}:
            result = _attach_longbridge_cash_anchor_watchlist(result)
        return result
    raise ValueError(f"未知策略岛：{framework_id}")


def _tracked_symbols_from_snapshot(framework_id: str, snapshot: dict[str, Any]) -> list[TrackedSymbol]:
    items: list[TrackedSymbol] = []
    if framework_id == "Growth_Engine":
        for row in snapshot.get("longbridge_growth_universe") or []:
            items.append(
                TrackedSymbol(
                    symbol=str(row.get("symbol") or "").strip().upper(),
                    name=str(row.get("name") or "").strip(),
                    market="US",
                    source="longbridge_growth_universe",
                    priority="broker_holding" if row.get("has_position") else "broker_watchlist",
                    notes=str(row.get("reason") or row.get("notes") or ""),
                )
            )
    else:
        for row in snapshot.get("positions") or []:
            items.append(
                TrackedSymbol(
                    symbol=str(row.get("symbol") or "").strip().upper(),
                    name=str(row.get("name") or "").strip(),
                    market=_normalize_market_value(row.get("market"), row.get("symbol")),
                    source="holding",
                    priority=str(row.get("currency") or ""),
                    notes=str(row.get("notes") or ""),
                )
            )
        for row in snapshot.get("longbridge_cash_anchor_watchlist") or []:
            items.append(
                TrackedSymbol(
                    symbol=str(row.get("symbol") or "").strip().upper(),
                    name=str(row.get("name") or "").strip(),
                    market="US",
                    source="longbridge_cash_anchor_watchlist",
                    priority="broker_watchlist_pinned" if row.get("is_pinned") else "broker_watchlist",
                    notes=str(row.get("reason") or row.get("group_name") or ""),
                )
            )
        for row in snapshot.get("watchlist") or []:
            items.append(
                TrackedSymbol(
                    symbol=str(row.get("symbol") or "").strip().upper(),
                    name=str(row.get("name") or "").strip(),
                    market=_normalize_market_value(row.get("market"), row.get("symbol")),
                    source="watchlist",
                    priority=str(row.get("priority") or ""),
                    notes=str(row.get("watch_reason") or row.get("trigger_condition") or ""),
                )
            )
    return _dedupe_tracked([item for item in items if item.symbol])


def _collect_market_data(symbols: list[TrackedSymbol]) -> dict[str, Any]:
    from src.market_data import fetch_market_data

    result: dict[str, Any] = {}
    for item in symbols:
        try:
            result[item.symbol] = fetch_market_data(item.symbol, market=item.market)
        except Exception as exc:
            result[item.symbol] = {
                "status": "error",
                "source": "market_data",
                "market": item.market,
                "symbol": item.symbol,
                "data": {},
                "error": str(exc),
            }
    return result


def _collect_symbol_intel(symbols: list[TrackedSymbol]) -> dict[str, Any]:
    from src.market_intel import fetch_company_announcements, fetch_company_news

    result: dict[str, Any] = {}
    for item in symbols:
        query_name = " ".join(part for part in [item.symbol, item.name] if part).strip()
        try:
            news = fetch_company_news(
                item.symbol,
                market=item.market,
                query=query_name,
                limit=MAX_INTEL_ITEMS_PER_SOURCE,
            )
        except Exception as exc:
            news = _intel_error("news", item, exc)
        try:
            announcements = fetch_company_announcements(
                item.symbol,
                market=item.market,
                query=query_name,
                limit=MAX_INTEL_ITEMS_PER_SOURCE,
                days=14,
            )
        except Exception as exc:
            announcements = _intel_error("announcement", item, exc)
        result[item.symbol] = {
            "news": _compact_intel_payload(news),
            "announcements": _compact_intel_payload(announcements),
        }
    return result


def _collect_research_dossier_summaries(framework_id: str, symbols: list[TrackedSymbol]) -> dict[str, Any]:
    from src.research_dossier import build_research_dossier_snapshot

    result: dict[str, Any] = {}
    for item in symbols:
        try:
            snapshot = build_research_dossier_snapshot(
                framework_id=framework_id,
                symbol=item.symbol,
                user_query=f"{item.symbol} {item.name}",
            )
            dossier = snapshot.get("dossier") or {}
            result[item.symbol] = {
                "exists": bool(snapshot.get("exists")),
                "path": snapshot.get("path"),
                "freshness": snapshot.get("freshness") or {},
                "core_thesis": dossier.get("core_thesis") or "",
                "why_i_bought": list(dossier.get("why_i_bought") or [])[:5],
                "bullish_case": list(dossier.get("bullish_case") or [])[:5],
                "bearish_case": list(dossier.get("bearish_case") or [])[:5],
                "risk_points": list(dossier.get("risk_points") or [])[:5],
                "exit_conditions": list(dossier.get("exit_conditions") or [])[:5],
                "open_questions": list(dossier.get("open_questions") or [])[:5],
            }
        except Exception as exc:
            result[item.symbol] = {"status": "error", "error": str(exc)}
    return result


def _attach_longbridge_growth_universe(snapshot: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(snapshot)
    try:
        from src.growth_universe import sync_growth_universe

        payload = sync_growth_universe()
    except Exception as exc:
        enriched["longbridge_growth_universe"] = []
        enriched["longbridge_growth_universe_error"] = str(exc)
        enriched["longbridge_growth_universe_policy"] = {
            "classification_rule": "长桥读取失败时，不使用本地手工 Growth 自选股回退。",
            "write_policy": "只读，不写入本地成长持仓或自选账本。",
        }
        return enriched

    universe = list(payload.get("universe") or [])
    enriched["longbridge_growth_universe"] = universe
    enriched["longbridge_growth_universe_source"] = payload
    enriched["longbridge_growth_universe_policy"] = {
        "classification_rule": payload.get("classification_rule") or "",
        "write_policy": payload.get("write_policy") or "read_only_context",
    }
    summary = dict(enriched.get("summary") or {})
    summary["longbridge_growth_universe_count"] = len(universe)
    summary["longbridge_growth_universe_excluded_count"] = (payload.get("summary") or {}).get("excluded_count", 0)
    enriched["summary"] = summary
    return enriched


def _attach_longbridge_cash_anchor_watchlist(snapshot: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(snapshot)
    try:
        from src.longbridge_provider import sync_longbridge_cash_anchor_watchlist

        payload = sync_longbridge_cash_anchor_watchlist()
    except Exception as exc:
        enriched["longbridge_cash_anchor_watchlist"] = []
        enriched["longbridge_cash_anchor_watchlist_error"] = str(exc)
        enriched["longbridge_cash_anchor_watchlist_policy"] = {
            "classification_rule": "长桥 watchlist 读取失败时，不阻断本地 Cash Anchor 美股复盘。",
            "write_policy": "只读，不写入 Cash Anchor 自选股账本。",
        }
        return enriched

    watchlist = list(payload.get("watchlist") or [])
    enriched["longbridge_cash_anchor_watchlist"] = watchlist
    enriched["longbridge_cash_anchor_watchlist_source"] = payload
    enriched["longbridge_cash_anchor_watchlist_policy"] = {
        "classification_rule": payload.get("classification_rule") or "",
        "write_policy": payload.get("write_policy") or "read_only_context",
    }
    summary = dict(enriched.get("summary") or {})
    summary["longbridge_cash_anchor_watchlist_count"] = len(watchlist)
    enriched["summary"] = summary
    return enriched


def _load_strategy_context(framework_id: str, market: str) -> str:
    framework_dir = FRAMEWORKS_DIR / framework_id
    files = [framework_dir / "constitution.md"]
    if market in {"CN", "US"}:
        bundle = _context_bundle(framework_id, market)
        if bundle and bundle != framework_id:
            files.append(framework_dir / "sub_frameworks" / f"{bundle}.md")
    elif market == "ALL":
        sub_frameworks = {
            "Cash_Anchor": ["CN_Dividend_Income", "US_Income_Options"],
            "Growth_Engine": ["US_Disruptive_Growth"],
        }[framework_id]
        files.extend(framework_dir / "sub_frameworks" / f"{name}.md" for name in sub_frameworks)
    loaded: list[str] = []
    for path in files:
        if path.exists():
            loaded.append(f"# 来源：{path}\n\n{path.read_text(encoding='utf-8')}")
    return "\n\n---\n\n".join(loaded)


def _report_dir(framework_id: str, workflow_type: str) -> Path:
    report_name = WEEKLY_REPORT_DIR if workflow_type == "weekly" else DAILY_REPORT_DIR
    return FRAMEWORKS_DIR / framework_id / "reports" / report_name


def _iter_records(framework_id: str, report_dir_name: str) -> list[dict[str, Any]]:
    path = FRAMEWORKS_DIR / framework_id / "reports" / report_dir_name
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for file_path in sorted(path.glob("*.jsonl")):
        with file_path.open("r", encoding="utf-8") as file:
            for line in file:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    record["_record_path"] = str(file_path)
                    records.append(record)
    return records


def _archive_scheduled_terminal_record(record: dict[str, Any], path: Path, *, chat_id: str | None) -> None:
    try:
        from src.context_logger import save_chat_session
        from src.decision_record import save_decision_record
        from src.state import AgentState, DisclosureRecord, PipelineStatus

        state = AgentState(
            user_input=(
                f"[scheduled_review] {record['workflow_type']} "
                f"{record['framework_id']} {record['market']} {record['review_date']}"
            ),
            chat_id=chat_id,
            trace_id=str(record.get("trace_id") or ""),
            framework_id=str(record.get("framework_id") or ""),
            context_bundle_id=str(record.get("context_bundle_id") or ""),
            loaded_context_files=_context_file_refs(record.get("context") or {}),
            route_reason="scheduler",
            draft_decision=str(record.get("result") or ""),
            final_answer=str(record.get("result") or ""),
            output_contract={
                "type": "scheduled_review",
                "workflow_type": record.get("workflow_type"),
                "market": record.get("market"),
                "record_path": str(path),
            },
            decision_snapshot={
                "scheduled_record_path": str(path),
                "status": record.get("status"),
                "tracked_symbol_count": record.get("tracked_symbol_count"),
            },
            audit_signal="PASS" if record.get("status") != "error" else "WARN",
            status=PipelineStatus.COMPLETED if record.get("status") != "error" else PipelineStatus.FAILED,
        )
        state.disclosed_data.append(
            DisclosureRecord(
                skill_name="scheduled_review_context",
                arguments={
                    "workflow_type": str(record.get("workflow_type") or ""),
                    "market": str(record.get("market") or ""),
                },
                payload={
                    "result": {
                        "status": record.get("status"),
                        "source": "scheduled_review",
                        "data_type": "scheduled_review_context",
                        "data": {
                            "record_path": str(path),
                            "tracked_symbol_count": record.get("tracked_symbol_count"),
                        },
                        "warnings": (record.get("context") or {}).get("data_gaps") or [],
                        "error": record.get("error") or "",
                    }
                },
            )
        )
        save_chat_session(state)
        save_decision_record(state)
    except Exception:
        return


def _format_scheduled_result(record: dict[str, Any], path: Path) -> str:
    status_text = "已完成" if record.get("status") == "ok" else "已跳过"
    header = (
        f"{record.get('framework_label')} {record.get('market')} "
        f"{record.get('workflow_label')} {status_text}：{record.get('review_date')}"
    )
    return "\n\n".join([header, str(record.get("result") or "").strip(), f"记录：{path}"]).strip()


def _empty_daily_result(
    framework_id: str,
    market: str,
    workflow_type: str,
    target_date: date,
    context: dict[str, Any],
) -> str:
    return (
        f"{FRAMEWORK_LABELS[framework_id]} {market} {WORKFLOW_LABELS[workflow_type]}未生成正式建议："
        f"{target_date.isoformat()} 未读取到该策略岛下的持仓或自选股。\n"
        "请先录入持仓或自选股，再执行该定时任务。\n"
        "数据缺口：\n"
        + "\n".join(f"- {item}" for item in context.get("data_gaps") or ["缺少持仓/自选股"])
    )


def _empty_weekly_result(framework_id: str, target_date: date, context: dict[str, Any]) -> str:
    return (
        f"{FRAMEWORK_LABELS[framework_id]} 周复盘未生成正式建议："
        f"{target_date.isoformat()} 未读取到过去一周日报。\n"
        "请先跑通交易日开盘计划和收盘复盘，再执行周复盘。\n"
        "数据缺口：\n"
        + "\n".join(f"- {item}" for item in context.get("data_gaps") or ["缺少过去一周日报"])
    )


def _workflow_instructions(framework_id: str, market: str, workflow_type: str) -> list[str]:
    if workflow_type == "premarket":
        return [
            "给出今日可执行操作建议，但不得假设已下单。",
            "必须区分持仓股和自选股；持仓给出持有、减仓、加仓、观察或禁动， 自选股给出是否进入观察/等待触发。",
            "必须引用上一交易日收盘复盘和最近周计划；没有记录时明确说明逻辑连续性缺口。",
            "Cash Anchor 侧重分红安全边际、现金流、仓位上限和正式披露；Growth Engine 侧重趋势、基本面变化、估值和风控触发。",
        ]
    if workflow_type == "close":
        return [
            "复盘今日变化，并和上一交易日收盘记录对照，判断逻辑是否延续、失效或需要降级。",
            "如果同日开盘计划存在，检查计划执行假设是否被市场验证或推翻。",
            "输出明日需要继续观察的触发条件和需要刷新研究档案的标的。",
            "不得用当天价格波动直接改写长期框架，只能提出待审议的框架修改建议。",
        ]
    return [
        "按策略岛独立复盘过去一周，不跨策略岛混用结论。",
        "汇总过去一周日报、新闻、公告、执行偏差和未解决问题。",
        "明确框架是否需要修改；只能给出修改建议，不能自动修改 constitution.md。",
        "输出下周计划、重点自选股新闻、持仓纪律和数据缺口。",
        f"当前市场范围：{market}；当前策略岛：{framework_id}。",
    ]


def _daily_data_gaps(
    snapshot: dict[str, Any],
    tracked: list[TrackedSymbol],
    market_data: dict[str, Any],
    intel: dict[str, Any],
    dossiers: dict[str, Any],
) -> list[str]:
    gaps: list[str] = []
    if not tracked:
        gaps.append("该市场没有读取到持仓或自选股。")
    for item in snapshot.get("missing_files") or []:
        gaps.append(f"缺少数据文件：{item}")
    if snapshot.get("longbridge_growth_universe_error"):
        gaps.append(f"长桥 Growth US universe 读取失败：{snapshot.get('longbridge_growth_universe_error')}")
    if snapshot.get("longbridge_cash_anchor_watchlist_error"):
        gaps.append(f"长桥 Cash Anchor US 自选股读取失败：{snapshot.get('longbridge_cash_anchor_watchlist_error')}")
    for symbol, payload in market_data.items():
        if payload.get("status") != "ok":
            gaps.append(f"{symbol} 行情不可用：{payload.get('error') or payload.get('status')}")
    for symbol, payload in intel.items():
        news = payload.get("news") or {}
        announcements = payload.get("announcements") or {}
        if not news.get("items") and not announcements.get("items"):
            gaps.append(f"{symbol} 新闻/公告没有可用条目。")
    for symbol, payload in dossiers.items():
        freshness = payload.get("freshness") or {}
        if payload.get("exists") and freshness.get("stale"):
            gaps.append(f"{symbol} 研究档案可能过期：{freshness.get('stale_reason') or 'stale'}")
    return _dedupe_text(gaps)


def _weekly_data_gaps(
    daily_records: list[dict[str, Any]],
    tracked: list[TrackedSymbol],
    intel: dict[str, Any],
    dossiers: dict[str, Any],
    *,
    framework_id: str,
) -> list[str]:
    gaps: list[str] = []
    if not daily_records:
        gaps.append("过去一周没有日报记录。")
    if not tracked:
        gaps.append("当前策略岛没有持仓或自选股。")
    markets = {str(record.get("market") or "") for record in daily_records}
    required_markets = ["US"] if framework_id == "Growth_Engine" else ["CN", "US"]
    for market in required_markets:
        if market not in markets:
            gaps.append(f"过去一周缺少 {market} 日报记录。")
    for symbol, payload in intel.items():
        news = payload.get("news") or {}
        announcements = payload.get("announcements") or {}
        if not news.get("items") and not announcements.get("items"):
            gaps.append(f"{symbol} 周复盘新闻/公告为空。")
    for symbol, payload in dossiers.items():
        freshness = payload.get("freshness") or {}
        if payload.get("exists") and freshness.get("stale"):
            gaps.append(f"{symbol} 研究档案可能过期：{freshness.get('stale_reason') or 'stale'}")
    return _dedupe_text(gaps)


def _research_dossier_notes(dossiers: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    missing = [symbol for symbol, payload in dossiers.items() if not payload.get("exists")]
    if missing:
        notes.append(
            "未建立研究档案的标的不会阻塞自动化复盘；如需长期判断保鲜，可后续补充："
            + ", ".join(missing[:12])
        )
    stale = []
    for symbol, payload in dossiers.items():
        freshness = payload.get("freshness") or {}
        if payload.get("exists") and freshness.get("stale"):
            stale.append(f"{symbol}({freshness.get('stale_reason') or 'stale'})")
    if stale:
        notes.append("以下研究档案可能过期，仅作为提示：" + ", ".join(stale[:12]))
    return notes


def _compact_records(records: list[dict[str, Any]], *, include_context: bool) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for record in records:
        row = {
            "record_id": record.get("record_id"),
            "created_at": record.get("created_at"),
            "review_date": record.get("review_date"),
            "framework_id": record.get("framework_id"),
            "market": record.get("market"),
            "workflow_type": record.get("workflow_type"),
            "workflow_label": record.get("workflow_label"),
            "status": record.get("status"),
            "tracked_symbol_count": record.get("tracked_symbol_count"),
            "result": _preview(str(record.get("result") or ""), limit=2500),
            "record_path": record.get("_record_path"),
        }
        if include_context:
            row["context"] = record.get("context") or {}
        result.append(row)
    return result


def _record_counts(records: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, Any] = {"total": len(records), "by_market": {}, "by_workflow_type": {}}
    for record in records:
        market = str(record.get("market") or "unknown")
        workflow = str(record.get("workflow_type") or "unknown")
        counts["by_market"][market] = counts["by_market"].get(market, 0) + 1
        counts["by_workflow_type"][workflow] = counts["by_workflow_type"].get(workflow, 0) + 1
    return counts


def _compact_intel_payload(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    items = list(data.get("items") or payload.get("items") or [])
    if not items and isinstance(data, dict):
        items = list(data.get("news") or data.get("announcements") or [])
    return {
        "status": payload.get("status"),
        "source": payload.get("source"),
        "error": payload.get("error") or "",
        "items": [_compact_intel_item(item) for item in items[:MAX_INTEL_ITEMS_PER_SOURCE]],
        "data_quality": payload.get("data_quality") or {},
        "source_chain": payload.get("source_chain") or [],
    }


def _compact_intel_item(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {"text": _preview(str(item), limit=300)}
    return {
        "title": item.get("title") or item.get("name") or "",
        "summary": _preview(str(item.get("summary") or item.get("category") or ""), limit=300),
        "published_at": item.get("published_at") or item.get("date") or "",
        "source": item.get("source") or item.get("provider") or "",
        "url": item.get("url") or "",
    }


def _intel_error(data_type: str, item: TrackedSymbol, exc: Exception) -> dict[str, Any]:
    return {
        "status": "error",
        "source": "market_intel",
        "data_type": data_type,
        "data": {"query": item.symbol, "items": []},
        "error": str(exc),
    }


def _validate_framework(framework_id: str) -> str:
    if framework_id not in VALID_FRAMEWORKS:
        raise ValueError(f"未知策略岛：{framework_id}")
    return framework_id


def _validate_market(market: str, *, allow_all: bool) -> str:
    clean = _normalize_market_value(market, "")
    if clean == "ALL" and allow_all:
        return clean
    if clean not in {"CN", "US"}:
        raise ValueError(f"未知市场：{market}")
    return clean


def _validate_framework_market(framework_id: str, market: str) -> None:
    if framework_id == "Growth_Engine" and market == "CN":
        raise ValueError("Growth_Engine 已停用非美股自动化；请使用 US 或 ALL。")


def _validate_workflow_type(workflow_type: str, *, allow_weekly: bool) -> str:
    clean = (workflow_type or "").strip().lower()
    valid = VALID_WORKFLOW_TYPES if allow_weekly else {"premarket", "close"}
    if clean not in valid:
        raise ValueError(f"未知自动化工作流：{workflow_type}")
    return clean


def _context_bundle(framework_id: str, market: str) -> str:
    return CONTEXT_BUNDLE_BY_FRAMEWORK_MARKET.get((framework_id, market), framework_id)


def _normalize_market_value(market: Any, symbol: Any) -> str:
    clean = str(market or "").strip().upper()
    if clean in {"A", "A股", "CN", "CHINA", "ASHARE", "A_SHARE"}:
        return "CN"
    if clean in {"US", "USA", "美股"}:
        return "US"
    if clean == "ALL":
        return "ALL"
    upper_symbol = str(symbol or "").upper()
    if upper_symbol.endswith(".US"):
        return "US"
    return clean or "CN"


def _matches_record(record: dict[str, Any], *, market: str | None, workflow_type: str | None) -> bool:
    if market and str(record.get("market") or "").upper() != _normalize_market_value(market, ""):
        return False
    if workflow_type and str(record.get("workflow_type") or "") != workflow_type:
        return False
    return True


def _record_date(record: dict[str, Any]) -> date | None:
    try:
        return date.fromisoformat(str(record.get("review_date") or ""))
    except ValueError:
        return None


def _dedupe_tracked(items: list[TrackedSymbol]) -> list[TrackedSymbol]:
    seen: set[tuple[str, str]] = set()
    result: list[TrackedSymbol] = []
    for item in items:
        key = (item.symbol.upper(), item.market.upper())
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _dedupe_text(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        clean = str(item or "").strip()
        if clean and clean not in result:
            result.append(clean)
    return result


def _context_file_refs(context: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    snapshot = context.get("snapshot") or {}
    snapshots = context.get("snapshots") or {}
    for payload in [snapshot, *list(snapshots.values())]:
        if isinstance(payload, dict):
            files = payload.get("data_files")
            if isinstance(files, dict):
                refs.extend(str(value) for value in files.values())
            watchlist_snapshot = payload.get("watchlist_snapshot")
            if isinstance(watchlist_snapshot, dict):
                files = watchlist_snapshot.get("data_files")
                if isinstance(files, dict):
                    refs.extend(str(value) for value in files.values())
    return sorted(set(refs))


def _trace_budget_start(*, trace_id: str, chat_id: str | None, framework_id: str) -> None:
    try:
        from src.budget_manager import trace_budget_start

        trace_budget_start(
            trace_id=trace_id,
            chat_id=chat_id,
            framework_id=framework_id,
            workflow="scheduled_review",
        )
    except Exception:
        return


def _trace_review_finished(
    trace_id: str,
    chat_id: str | None,
    framework_id: str,
    record: dict[str, Any],
    path: Path,
) -> None:
    trace_event(
        trace_id=trace_id,
        event_type="scheduled_review_finished",
        chat_id=chat_id,
        framework_id=framework_id,
        agent_role="scheduler",
        status=str(record.get("status") or "ok"),
        output_preview=str(record.get("result") or ""),
        metadata={
            "record_path": str(path),
            "workflow_type": record.get("workflow_type"),
            "market": record.get("market"),
            "tracked_symbol_count": record.get("tracked_symbol_count"),
        },
    )


def _preview(text: str, *, limit: int) -> str:
    clean = " ".join(text.split())
    return clean[:limit]
