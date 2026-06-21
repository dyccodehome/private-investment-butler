"""Read-only health summary for scheduled investment workflows."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from src.init import FRAMEWORKS_DIR, RUNTIME_DIR


SCHEDULER_RUNS_PATH = RUNTIME_DIR / "scheduler" / "runs.jsonl"
REPORT_SUBDIRS = ("daily_reviews", "weekly_reviews")
MAX_RECENT_ITEMS = 8


def summarize_scheduled_health(
    *,
    runs_path: Path = SCHEDULER_RUNS_PATH,
    frameworks_dir: Path = FRAMEWORKS_DIR,
    current_job_names: set[str] | None = None,
) -> dict[str, Any]:
    """Summarize scheduler run logs and persisted scheduled review reports."""

    runs = _read_jsonl(runs_path)
    reports = _read_report_records(frameworks_dir)
    enabled_jobs = set(current_job_names or set())
    obsolete_job_names = sorted(
        {
            str(row.get("job") or "")
            for row in runs
            if row.get("job") and enabled_jobs and str(row.get("job")) not in enabled_jobs
        }
    )

    scheduler_summary = _summarize_runs(runs, obsolete_job_names)
    report_summary = _summarize_reports(reports)
    findings = _build_findings(scheduler_summary, report_summary)

    return {
        "generated_at": datetime.now().replace(microsecond=0).isoformat(),
        "runs_path": str(runs_path),
        "frameworks_dir": str(frameworks_dir),
        "current_enabled_jobs": sorted(enabled_jobs),
        "scheduler_runs": scheduler_summary,
        "reports": report_summary,
        "findings": findings,
    }


def format_scheduled_health(summary: dict[str, Any], *, limit: int = MAX_RECENT_ITEMS) -> str:
    """Format scheduled health summary for CLI/Feishu."""

    runs = summary.get("scheduler_runs") or {}
    reports = summary.get("reports") or {}
    findings = list(summary.get("findings") or [])
    lines = [
        "定时任务健康检查",
        f"生成时间：{summary.get('generated_at')}",
        "",
        "运行日志：",
        f"- 总运行记录：{runs.get('total', 0)}",
        f"- 状态分布：{_format_counter(runs.get('status_counts') or {})}",
        f"- 当前配置外的历史任务：{_format_items(runs.get('obsolete_job_names') or [])}",
        "",
        "报告质量：",
        f"- 总报告记录：{reports.get('total', 0)}",
        f"- 状态分布：{_format_counter(reports.get('status_counts') or {})}",
        f"- tracked_symbol_count=0：{len(reports.get('zero_tracked_records') or [])}",
        f"- 长桥相关数据缺口：{len(reports.get('longbridge_gap_records') or [])}",
        f"- US/ALL 报告缺 account_activity：{len(reports.get('records_missing_account_activity') or [])}",
        f"- US/ALL 报告缺 longbridge_market_context：{len(reports.get('records_missing_longbridge_market_context') or [])}",
        f"- Growth 报告缺 research_engine：{len(reports.get('growth_records_missing_research_engine') or [])}",
        f"- Growth 报告缺 operation_framework：{len(reports.get('growth_records_missing_operation_framework') or [])}",
    ]

    if findings:
        lines.extend(["", "主要发现："])
        lines.extend(f"- {item}" for item in findings[:limit])

    recent_failures = list(runs.get("recent_failures") or [])
    if recent_failures:
        lines.extend(["", f"最近失败任务（最多 {limit} 条）："])
        for item in recent_failures[:limit]:
            lines.append(
                "- "
                f"{item.get('created_at', '')} "
                f"{item.get('job', '')} "
                f"{item.get('market', '')} "
                f"{_truncate(str(item.get('error') or item.get('result_preview') or ''), 120)}"
            )

    zero_tracked = list(reports.get("zero_tracked_records") or [])
    if zero_tracked:
        lines.extend(["", f"空标的报告（最多 {limit} 条）："])
        for item in zero_tracked[:limit]:
            lines.append(
                "- "
                f"{item.get('review_date', '')} "
                f"{item.get('framework_id', '')} "
                f"{item.get('market', '')} "
                f"{item.get('workflow_type', '')} "
                f"{_truncate(str(item.get('primary_gap') or ''), 120)}"
            )

    data_gaps = reports.get("top_data_gaps") or []
    if data_gaps:
        lines.extend(["", f"高频数据缺口（最多 {limit} 条）："])
        for item in data_gaps[:limit]:
            lines.append(f"- {item.get('count', 0)}x {_truncate(str(item.get('gap') or ''), 140)}")

    return "\n".join(lines).strip()


def _summarize_runs(runs: list[dict[str, Any]], obsolete_job_names: list[str]) -> dict[str, Any]:
    status_counts = Counter(str(row.get("status") or "unknown") for row in runs)
    job_counts = Counter(str(row.get("job") or "unknown") for row in runs)
    recent = _sort_by_created_at(runs, reverse=True)
    failures = [
        _run_brief(row)
        for row in recent
        if str(row.get("status") or "") == "error" or row.get("error")
    ]
    skipped = [_run_brief(row) for row in recent if str(row.get("status") or "") == "skipped"]
    return {
        "total": len(runs),
        "status_counts": dict(status_counts),
        "job_counts": dict(job_counts),
        "obsolete_job_names": obsolete_job_names,
        "recent_failures": failures[:MAX_RECENT_ITEMS],
        "recent_skipped": skipped[:MAX_RECENT_ITEMS],
        "latest_run_by_job": _latest_by_key(runs, "job"),
    }


def _summarize_reports(records: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts = Counter(str(row.get("status") or "unknown") for row in records)
    framework_counts = Counter(str(row.get("framework_id") or "unknown") for row in records)
    workflow_counts = Counter(str(row.get("workflow_type") or "unknown") for row in records)
    data_gap_counts: Counter[str] = Counter()
    zero_tracked: list[dict[str, Any]] = []
    longbridge_gaps: list[dict[str, Any]] = []
    missing_research: list[dict[str, Any]] = []
    missing_operation: list[dict[str, Any]] = []
    missing_account_activity: list[dict[str, Any]] = []
    missing_market_context: list[dict[str, Any]] = []
    empty_results: list[dict[str, Any]] = []

    for record in _sort_by_created_at(records, reverse=True):
        context = record.get("context") if isinstance(record.get("context"), dict) else {}
        gaps = [str(item) for item in context.get("data_gaps") or []]
        for gap in gaps:
            data_gap_counts[gap] += 1
        brief = _report_brief(record, gaps)
        if int(record.get("tracked_symbol_count") or 0) == 0:
            zero_tracked.append(brief)
        if any(_contains_longbridge(gap) for gap in gaps):
            longbridge_gaps.append(brief)
        if str(record.get("market") or "") in {"US", "ALL"} and not _has_account_activity_context(context):
            missing_account_activity.append(brief)
        if str(record.get("market") or "") in {"US", "ALL"} and not _has_longbridge_market_context(context):
            missing_market_context.append(brief)
        if str(record.get("framework_id") or "") == "Growth_Engine":
            if not isinstance(context.get("research_engine"), dict):
                missing_research.append(brief)
            if not isinstance(context.get("operation_framework"), dict):
                missing_operation.append(brief)
        if not str(record.get("result") or "").strip():
            empty_results.append(brief)

    return {
        "total": len(records),
        "status_counts": dict(status_counts),
        "framework_counts": dict(framework_counts),
        "workflow_counts": dict(workflow_counts),
        "zero_tracked_records": zero_tracked[:MAX_RECENT_ITEMS],
        "longbridge_gap_records": longbridge_gaps[:MAX_RECENT_ITEMS],
        "records_missing_account_activity": missing_account_activity[:MAX_RECENT_ITEMS],
        "records_missing_longbridge_market_context": missing_market_context[:MAX_RECENT_ITEMS],
        "growth_records_missing_research_engine": missing_research[:MAX_RECENT_ITEMS],
        "growth_records_missing_operation_framework": missing_operation[:MAX_RECENT_ITEMS],
        "empty_result_records": empty_results[:MAX_RECENT_ITEMS],
        "top_data_gaps": [
            {"gap": gap, "count": count}
            for gap, count in data_gap_counts.most_common(MAX_RECENT_ITEMS)
        ],
        "latest_report_by_framework_workflow": _latest_by_composite(records, ("framework_id", "market", "workflow_type")),
    }


def _build_findings(runs: dict[str, Any], reports: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    run_status_counts = runs.get("status_counts") or {}
    error_count = int(run_status_counts.get("error") or 0)
    if error_count:
        recent_failure = (runs.get("recent_failures") or [{}])[0]
        findings.append(
            f"定时任务存在 {error_count} 条 error；最近失败任务是 "
            f"{recent_failure.get('job', 'unknown')}，错误："
            f"{_truncate(str(recent_failure.get('error') or ''), 100)}"
        )
    obsolete = runs.get("obsolete_job_names") or []
    if obsolete:
        findings.append(f"运行日志中仍能看到当前配置外的历史任务：{', '.join(obsolete)}。这些是历史记录，不代表当前 scheduler 还会继续触发。")

    report_status_counts = reports.get("status_counts") or {}
    skipped_reports = int(report_status_counts.get("skipped") or 0)
    if skipped_reports:
        findings.append(f"报告中有 {skipped_reports} 条 skipped，说明对应工作流到达了报告层，但没有足够标的或日报生成正式建议。")
    zero_count = len(reports.get("zero_tracked_records") or [])
    if zero_count:
        findings.append(f"最近有 {zero_count} 条报告 tracked_symbol_count=0；Growth 场景通常指向长桥 universe 未读到数据。")
    longbridge_count = len(reports.get("longbridge_gap_records") or [])
    if longbridge_count:
        findings.append(f"最近有 {longbridge_count} 条报告包含长桥数据缺口，需要优先确认 longbridge CLI、网络和本机权限。")
    missing_account = len(reports.get("records_missing_account_activity") or [])
    if missing_account:
        findings.append(f"最近 US/ALL 报告中有 {missing_account} 条没有 account_activity；账户/成交接入后的新报告应包含该字段。")
    missing_market = len(reports.get("records_missing_longbridge_market_context") or [])
    if missing_market:
        findings.append(f"最近 US/ALL 报告中有 {missing_market} 条没有 longbridge_market_context；行情接入后的新报告应包含该字段。")
    missing_research = len(reports.get("growth_records_missing_research_engine") or [])
    if missing_research:
        findings.append(f"最近 Growth 报告中有 {missing_research} 条没有 research_engine 字段；投研层上线后的新报告应包含该字段。")
    missing_operation = len(reports.get("growth_records_missing_operation_framework") or [])
    if missing_operation:
        findings.append(f"最近 Growth 报告中有 {missing_operation} 条没有 operation_framework 字段；操作框架上线后的新报告应包含该字段。")
    if reports.get("empty_result_records"):
        findings.append("存在 result 为空的报告记录，需要检查报告持久化或 LLM 返回。")
    if not findings:
        findings.append("未发现 error、空标的报告或关键结构缺失。")
    return findings


def _read_report_records(frameworks_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not frameworks_dir.exists():
        return records
    for framework_dir in frameworks_dir.iterdir():
        if not framework_dir.is_dir():
            continue
        reports_dir = framework_dir / "reports"
        for subdir in REPORT_SUBDIRS:
            path = reports_dir / subdir
            if not path.exists():
                continue
            for file_path in sorted(path.glob("*.jsonl")):
                for row in _read_jsonl(file_path):
                    row["_path"] = str(file_path)
                    records.append(row)
    return records


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            clean = line.strip()
            if not clean:
                continue
            try:
                row = json.loads(clean)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _sort_by_created_at(records: list[dict[str, Any]], *, reverse: bool) -> list[dict[str, Any]]:
    return sorted(
        records,
        key=lambda row: (str(row.get("created_at") or ""), str(row.get("review_date") or ""), str(row.get("run_key") or "")),
        reverse=reverse,
    )


def _latest_by_key(records: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in _sort_by_created_at(records, reverse=True):
        name = str(row.get(key) or "")
        if name and name not in latest:
            latest[name] = _run_brief(row)
    return latest


def _latest_by_composite(records: list[dict[str, Any]], keys: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in _sort_by_created_at(records, reverse=True):
        name = ":".join(str(row.get(key) or "") for key in keys)
        if name and name not in latest:
            latest[name] = _report_brief(row, [])
    return latest


def _run_brief(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_key": row.get("run_key"),
        "job": row.get("job"),
        "job_type": row.get("job_type"),
        "market": row.get("market"),
        "status": row.get("status"),
        "dry_run": row.get("dry_run"),
        "error": row.get("error"),
        "result_preview": row.get("result_preview"),
        "created_at": row.get("created_at"),
    }


def _report_brief(record: dict[str, Any], gaps: list[str]) -> dict[str, Any]:
    return {
        "record_id": record.get("record_id"),
        "review_date": record.get("review_date"),
        "created_at": record.get("created_at"),
        "framework_id": record.get("framework_id"),
        "market": record.get("market"),
        "workflow_type": record.get("workflow_type"),
        "status": record.get("status"),
        "tracked_symbol_count": record.get("tracked_symbol_count"),
        "primary_gap": gaps[0] if gaps else "",
        "path": record.get("_path"),
    }


def _contains_longbridge(text: str) -> bool:
    lower = text.lower()
    return "longbridge" in lower or "长桥" in text


def _has_account_activity_context(context: dict[str, Any]) -> bool:
    account_activity = context.get("account_activity")
    if isinstance(account_activity, dict) and account_activity:
        return True
    by_market = context.get("account_activity_by_market")
    if isinstance(by_market, dict) and by_market:
        return any(isinstance(item, dict) and item for item in by_market.values())
    return False


def _has_longbridge_market_context(context: dict[str, Any]) -> bool:
    market_context = context.get("longbridge_market_context")
    if not isinstance(market_context, dict) or not market_context:
        return False
    return bool(market_context.get("symbol_data") or market_context.get("status") in {"empty", "not_applicable"})


def _format_counter(counter: dict[str, Any]) -> str:
    if not counter:
        return "无"
    return ", ".join(f"{key}={value}" for key, value in sorted(counter.items()))


def _format_items(items: list[str]) -> str:
    return ", ".join(items) if items else "无"


def _truncate(text: str, limit: int) -> str:
    clean = " ".join(text.split())
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 3)] + "..."
