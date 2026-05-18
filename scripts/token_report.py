#!/usr/bin/env python3
"""汇总本地 Token 用量 JSONL 日志。

用法：
  python3 scripts/token_report.py
  python3 scripts/token_report.py --date 2026-05-17
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOKEN_USAGE_DIR = PROJECT_ROOT / "runtime" / "token_usage"


def main() -> None:
    args = _parse_args()
    records = _load_records(args.date)
    if not records:
        print("No token usage records found.")
        return

    print(f"Token Usage Report ({args.date})")
    print("=" * 72)
    _print_totals(records)
    _print_group(records, "agent_role", "By Agent Role")
    _print_group(records, "framework_id", "By Framework")
    _print_group(records, "call_site", "By Call Site")
    _print_top(records, args.top)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"), help="YYYY-MM-DD")
    parser.add_argument("--top", type=int, default=10, help="Top expensive calls to show")
    return parser.parse_args()


def _load_records(date: str) -> list[dict[str, Any]]:
    path = TOKEN_USAGE_DIR / f"{date}.jsonl"
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def _print_totals(records: list[dict[str, Any]]) -> None:
    total = sum(int(row.get("total_tokens") or 0) for row in records)
    input_tokens = sum(int(row.get("input_tokens") or 0) for row in records)
    output_tokens = sum(int(row.get("output_tokens") or 0) for row in records)
    reasoning_tokens = sum(int(row.get("reasoning_tokens") or 0) for row in records)
    print(f"Calls: {len(records)}")
    print(f"Total tokens: {total}")
    print(f"Input: {input_tokens} | Output: {output_tokens} | Reasoning: {reasoning_tokens}")
    print()


def _print_group(records: list[dict[str, Any]], key: str, title: str) -> None:
    grouped: dict[str, int] = defaultdict(int)
    for row in records:
        grouped[str(row.get(key) or "unknown")] += int(row.get("total_tokens") or 0)

    print(title)
    print("-" * 72)
    for name, total in sorted(grouped.items(), key=lambda item: item[1], reverse=True):
        print(f"{name:36} {total:10}")
    print()


def _print_top(records: list[dict[str, Any]], limit: int) -> None:
    print(f"Top {limit} Expensive Calls")
    print("-" * 72)
    sorted_rows = sorted(records, key=lambda row: int(row.get("total_tokens") or 0), reverse=True)
    for row in sorted_rows[:limit]:
        print(
            f"{int(row.get('total_tokens') or 0):8} | "
            f"{row.get('agent_role') or 'unknown':8} | "
            f"{row.get('framework_id') or 'unknown':22} | "
            f"{row.get('call_site') or 'unknown'}"
        )
        print(f"         query: {(row.get('user_query') or '')[:100]}")
        print(f"         fingerprint: {row.get('prompt_fingerprint')}")


if __name__ == "__main__":
    main()
