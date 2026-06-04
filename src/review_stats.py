"""Decision review and backtest-readiness statistics."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from src.init import RUNTIME_DIR


DECISION_DIR = RUNTIME_DIR / "decisions"


def load_decision_records(
    *,
    date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    decision_dir: Path = DECISION_DIR,
) -> list[dict[str, Any]]:
    """Load decision JSONL records for a day or date range."""

    records: list[dict[str, Any]] = []
    for path in _decision_paths(date=date, start_date=start_date, end_date=end_date, decision_dir=decision_dir):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                records.append(row)
    return records


def summarize_decisions(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate decision records for review and future backtesting."""

    by_framework: Counter[str] = Counter()
    by_context_bundle: Counter[str] = Counter()
    by_decision_type: Counter[str] = Counter()
    by_action_type: Counter[str] = Counter()
    by_audit_signal: Counter[str] = Counter()
    by_status: Counter[str] = Counter()
    by_symbol: Counter[str] = Counter()
    contract_status: Counter[str] = Counter()
    contract_missing_sections: Counter[str] = Counter()
    stale_or_unknown_blocks: Counter[str] = Counter()
    coverage_status: Counter[str] = Counter()
    limitations: Counter[str] = Counter()
    rejected_count = 0
    human_approval_count = 0
    backtest_ready_count = 0
    outcome_count = 0

    for row in records:
        snapshot = row.get("decision_snapshot") if isinstance(row.get("decision_snapshot"), dict) else {}
        data_quality = row.get("data_quality_summary") if isinstance(row.get("data_quality_summary"), dict) else {}
        contract = row.get("output_contract") if isinstance(row.get("output_contract"), dict) else {}
        if not contract and isinstance(snapshot.get("output_contract"), dict):
            contract = snapshot["output_contract"]

        by_framework[_clean(row.get("framework_id"))] += 1
        by_context_bundle[_clean(row.get("context_bundle_id") or snapshot.get("context_bundle_id"))] += 1
        by_decision_type[_clean(row.get("decision_type"))] += 1
        by_action_type[_clean(snapshot.get("action_type"))] += 1
        by_audit_signal[_clean(row.get("audit_signal"))] += 1
        by_status[_clean(row.get("status"))] += 1

        symbol = _clean(snapshot.get("symbol"))
        if symbol != "unknown":
            by_symbol[symbol] += 1

        signal = str(row.get("audit_signal") or "")
        if signal == "REJECT" or row.get("circuit_breaker") == "triggered":
            rejected_count += 1
        if row.get("requires_human_approval"):
            human_approval_count += 1

        contract_status[_clean(contract.get("status"))] += 1
        for section in contract.get("missing_sections") or []:
            contract_missing_sections[str(section)] += 1

        for key, value in (data_quality.get("coverage") or {}).items():
            coverage_status[f"{key}:{value}"] += 1
        for block in data_quality.get("stale_or_unknown_blocks") or []:
            stale_or_unknown_blocks[str(block)] += 1
        for item in data_quality.get("limitations") or []:
            limitations[str(item)] += 1

        if _is_backtest_ready(snapshot):
            backtest_ready_count += 1
        if isinstance(row.get("review_outcome"), dict) or isinstance(row.get("backtest"), dict):
            outcome_count += 1

    total = len(records)
    return {
        "generated_at": datetime.now().replace(microsecond=0).isoformat(),
        "total_records": total,
        "by_framework": dict(by_framework),
        "by_context_bundle": dict(by_context_bundle),
        "by_decision_type": dict(by_decision_type),
        "by_action_type": dict(by_action_type),
        "by_audit_signal": dict(by_audit_signal),
        "by_status": dict(by_status),
        "top_symbols": dict(by_symbol.most_common(20)),
        "rejected_count": rejected_count,
        "human_approval_count": human_approval_count,
        "contract": {
            "status_counts": dict(contract_status),
            "missing_sections": dict(contract_missing_sections),
        },
        "data_quality": {
            "coverage_status": dict(coverage_status),
            "stale_or_unknown_blocks": dict(stale_or_unknown_blocks),
            "top_limitations": dict(limitations.most_common(20)),
        },
        "backtest_readiness": {
            "ready_records": backtest_ready_count,
            "pending_records": max(total - outcome_count, 0),
            "records_with_outcome": outcome_count,
            "note": "收益回测只统计已有 outcome/backtest 字段的记录；未落地结果的样本只计入待回测池。",
        },
    }


def decision_review_summary(
    *,
    date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    decision_dir: Path = DECISION_DIR,
) -> dict[str, Any]:
    records = load_decision_records(
        date=date,
        start_date=start_date,
        end_date=end_date,
        decision_dir=decision_dir,
    )
    return summarize_decisions(records)


def _decision_paths(
    *,
    date: str | None,
    start_date: str | None,
    end_date: str | None,
    decision_dir: Path,
) -> list[Path]:
    if date:
        path = decision_dir / f"{date}.jsonl"
        return [path] if path.exists() else []
    if not decision_dir.exists():
        return []
    paths = sorted(decision_dir.glob("*.jsonl"))
    if not start_date and not end_date:
        return paths
    return [
        path
        for path in paths
        if (not start_date or path.stem >= start_date) and (not end_date or path.stem <= end_date)
    ]


def _is_backtest_ready(snapshot: dict[str, Any]) -> bool:
    action = str(snapshot.get("action_type") or "")
    symbol = str(snapshot.get("symbol") or "")
    return bool(symbol and action in {"buy", "add", "sell", "reduce", "hold", "watch"})


def _clean(value: Any) -> str:
    text = str(value or "").strip()
    return text if text else "unknown"
