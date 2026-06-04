#!/usr/bin/env python3
"""Summarize local decision records for review/backtest readiness."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.review_stats import decision_review_summary


def main() -> None:
    args = _parse_args()
    summary = decision_review_summary(
        date=args.date,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    _print_summary(summary, args)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Decision review statistics.")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"), help="YYYY-MM-DD")
    parser.add_argument("--start-date", default="", help="Optional range start YYYY-MM-DD")
    parser.add_argument("--end-date", default="", help="Optional range end YYYY-MM-DD")
    parser.add_argument("--json", action="store_true", help="Print raw JSON summary.")
    args = parser.parse_args()
    if args.start_date or args.end_date:
        args.date = ""
    return args


def _print_summary(summary: dict[str, Any], args: argparse.Namespace) -> None:
    label = args.date or f"{args.start_date or 'begin'}..{args.end_date or 'end'}"
    print(f"Decision Review Report ({label})")
    print("=" * 72)
    print(f"Records: {summary['total_records']}")
    print(f"Rejected: {summary['rejected_count']} | Human approval: {summary['human_approval_count']}")
    readiness = summary["backtest_readiness"]
    print(
        "Backtest readiness: "
        f"ready={readiness['ready_records']} "
        f"pending={readiness['pending_records']} "
        f"with_outcome={readiness['records_with_outcome']}"
    )
    print()
    _print_group("By Framework", summary["by_framework"])
    _print_group("By Action", summary["by_action_type"])
    _print_group("By Audit Signal", summary["by_audit_signal"])
    _print_group("Contract Missing Sections", summary["contract"]["missing_sections"])
    _print_group("Data Quality Gaps", summary["data_quality"]["stale_or_unknown_blocks"])
    _print_group("Top Symbols", summary["top_symbols"])


def _print_group(title: str, values: dict[str, Any]) -> None:
    print(title)
    print("-" * 72)
    if not values:
        print("(none)")
    for key, value in sorted(values.items(), key=lambda item: int(item[1]), reverse=True):
        print(f"{key:36} {value:8}")
    print()


if __name__ == "__main__":
    main()
