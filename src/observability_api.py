"""本地可观测性面板 API。"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from src.cost_meter import daily_cost_summary
from src.init import PROJECT_ROOT, RUNTIME_DIR


router = APIRouter()
TRACE_DIR = RUNTIME_DIR / "traces"
WEB_DIR = PROJECT_ROOT / "web" / "observability_dashboard"


@router.get("/observability", response_class=HTMLResponse)
def observability_page() -> str:
    """返回本地观测面板页面。"""

    path = WEB_DIR / "index.html"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return "<h1>Observability dashboard missing</h1>"


@router.get("/observability/app.js")
def observability_js() -> HTMLResponse:
    """返回面板脚本。"""

    return HTMLResponse((WEB_DIR / "app.js").read_text(encoding="utf-8"), media_type="application/javascript")


@router.get("/observability/style.css")
def observability_css() -> HTMLResponse:
    """返回面板样式。"""

    return HTMLResponse((WEB_DIR / "style.css").read_text(encoding="utf-8"), media_type="text/css")


@router.get("/api/traces")
def list_traces(date: str | None = None) -> dict[str, Any]:
    """按 trace_id 汇总指定日期的链路。"""

    date = date or datetime.now().strftime("%Y-%m-%d")
    events = _load_trace_events(date)
    traces: dict[str, dict[str, Any]] = {}
    for event in events:
        trace_id = str(event.get("trace_id") or "unknown")
        item = traces.setdefault(
            trace_id,
            {
                "trace_id": trace_id,
                "started_at": event.get("timestamp"),
                "last_at": event.get("timestamp"),
                "chat_id": event.get("chat_id"),
                "framework_id": event.get("framework_id"),
                "status": event.get("status"),
                "user_query": event.get("input_preview"),
                "final_output": "",
                "event_count": 0,
                "total_tokens": 0,
                "risk_flags": set(),
            },
        )
        item["last_at"] = event.get("timestamp")
        item["framework_id"] = event.get("framework_id") or item.get("framework_id")
        item["status"] = event.get("status") or item.get("status")
        item["event_count"] += 1
        token_usage = event.get("token_usage") or {}
        item["total_tokens"] += int(token_usage.get("total_tokens") or 0)
        for flag in event.get("risk_flags") or []:
            item["risk_flags"].add(flag)
        if event.get("event_type") == "final_message_sent":
            item["final_output"] = event.get("output_preview") or ""

    rows = []
    for item in traces.values():
        item["risk_flags"] = sorted(item["risk_flags"])
        rows.append(item)
    rows.sort(key=lambda row: str(row.get("last_at") or ""), reverse=True)
    return {"date": date, "traces": rows}


@router.get("/api/traces/{trace_id}")
def trace_detail(trace_id: str, date: str | None = None) -> dict[str, Any]:
    """返回单条 trace 的完整时间线。"""

    date = date or datetime.now().strftime("%Y-%m-%d")
    events = [event for event in _load_trace_events(date) if str(event.get("trace_id")) == trace_id]
    return {"date": date, "trace_id": trace_id, "events": events}


@router.get("/api/observability/summary")
def observability_summary(date: str | None = None) -> dict[str, Any]:
    """返回观测总览指标。"""

    date = date or datetime.now().strftime("%Y-%m-%d")
    events = _load_trace_events(date)
    event_count_by_type: dict[str, int] = defaultdict(int)
    risk_count: dict[str, int] = defaultdict(int)
    traces = set()
    total_latency = 0
    latency_count = 0

    for event in events:
        traces.add(event.get("trace_id"))
        event_count_by_type[str(event.get("event_type") or "unknown")] += 1
        for flag in event.get("risk_flags") or []:
            risk_count[str(flag)] += 1
        if event.get("latency_ms") is not None:
            total_latency += int(event.get("latency_ms") or 0)
            latency_count += 1

    return {
        "date": date,
        "trace_count": len(traces),
        "event_count": len(events),
        "event_count_by_type": dict(sorted(event_count_by_type.items())),
        "risk_count": dict(sorted(risk_count.items(), key=lambda item: item[1], reverse=True)),
        "avg_latency_ms": int(total_latency / latency_count) if latency_count else 0,
        "cost": daily_cost_summary(date),
    }


def _load_trace_events(date: str) -> list[dict[str, Any]]:
    path = TRACE_DIR / f"{date}.jsonl"
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events
