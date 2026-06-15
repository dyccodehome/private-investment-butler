"""Cash Anchor watchlist ledger.

This module is deterministic local storage only. It gives scheduled Cash
Anchor workflows the same holdings/watchlist split that Growth Engine already
has without mixing it into portfolio accounting.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

from src.init import FRAMEWORKS_DIR


CASH_ANCHOR_DIR = FRAMEWORKS_DIR / "Cash_Anchor"
DATA_DIR = CASH_ANCHOR_DIR / "data"
TEMPLATE_DIR = CASH_ANCHOR_DIR / "data_templates"
WATCHLIST_PATH = DATA_DIR / "cash_watchlist.csv"


@dataclass(frozen=True)
class CashWatchItem:
    symbol: str
    name: str
    market: str
    category: str
    priority: str
    watch_reason: str
    trigger_condition: str
    status: str = "active"
    last_review_at: str = ""
    notes: str = ""


def upsert_cash_watch_item(
    *,
    symbol: str,
    name: str = "",
    market: str = "CN",
    category: str = "dividend",
    priority: str = "medium",
    watch_reason: str = "",
    trigger_condition: str = "",
    status: str = "active",
    last_review_at: str = "",
    notes: str = "",
) -> dict[str, Any]:
    """Create or update one Cash Anchor watchlist item."""

    clean_symbol = _required_symbol(symbol)
    current = CashWatchItem(
        symbol=clean_symbol,
        name=name or clean_symbol,
        market=_normalize_market(market),
        category=category or "dividend",
        priority=priority or "medium",
        watch_reason=watch_reason,
        trigger_condition=trigger_condition,
        status=status or "active",
        last_review_at=last_review_at,
        notes=notes,
    )
    _ensure_watchlist_file()
    rows = read_cash_watchlist()
    replaced = False
    next_rows: list[CashWatchItem] = []
    for item in rows:
        if item.symbol.upper() == clean_symbol.upper():
            next_rows.append(current)
            replaced = True
        else:
            next_rows.append(item)
    if not replaced:
        next_rows.append(current)
    _write_cash_watchlist(next_rows)
    snapshot = build_cash_watchlist_snapshot()
    snapshot["updated_watch_item"] = asdict(current)
    snapshot["watch_action"] = "updated" if replaced else "created"
    return snapshot


def build_cash_watchlist_snapshot(market: str | None = None) -> dict[str, Any]:
    """Build a local Cash Anchor watchlist snapshot."""

    market_filter = _normalize_market(market) if market else ""
    items = [
        item
        for item in read_cash_watchlist()
        if not market_filter or _normalize_market(item.market) == market_filter
    ]
    return {
        "as_of": date.today().isoformat(),
        "market_filter": market_filter,
        "data_files": {"watchlist": str(WATCHLIST_PATH)},
        "missing_files": [str(WATCHLIST_PATH)] if not WATCHLIST_PATH.exists() else [],
        "summary": {
            "watchlist_count": len(items),
            "by_market": _count_by([asdict(item) for item in items], "market"),
            "by_category": _count_by([asdict(item) for item in items], "category"),
            "by_priority": _count_by([asdict(item) for item in items], "priority"),
        },
        "watchlist": [asdict(item) for item in items],
        "template_files": {"watchlist": str(TEMPLATE_DIR / "cash_watchlist.csv")},
    }


def read_cash_watchlist() -> list[CashWatchItem]:
    if not WATCHLIST_PATH.exists():
        return []
    rows = _read_csv(WATCHLIST_PATH)
    return [
        CashWatchItem(
            symbol=str(row.get("symbol") or "").strip(),
            name=str(row.get("name") or "").strip(),
            market=_normalize_market(str(row.get("market") or "")),
            category=str(row.get("category") or "dividend").strip(),
            priority=str(row.get("priority") or "medium").strip(),
            watch_reason=str(row.get("watch_reason") or "").strip(),
            trigger_condition=str(row.get("trigger_condition") or "").strip(),
            status=str(row.get("status") or "active").strip(),
            last_review_at=str(row.get("last_review_at") or "").strip(),
            notes=str(row.get("notes") or "").strip(),
        )
        for row in rows
        if str(row.get("symbol") or "").strip()
    ]


def format_cash_watchlist_snapshot(snapshot: dict[str, Any]) -> str:
    lines = [
        "Cash Anchor 自选股快照：",
        f"- 日期：{snapshot['as_of']}",
        f"- 市场过滤：{snapshot['market_filter'] or '全部'}",
        f"- 自选数：{snapshot['summary']['watchlist_count']}",
        "",
        "自选股：",
    ]
    if snapshot["watchlist"]:
        for item in snapshot["watchlist"]:
            lines.append(
                f"- {item['symbol']} {item['name']}：{item['category']}，"
                f"优先级 {item['priority']}，触发条件：{item['trigger_condition'] or '未填写'}"
            )
    else:
        lines.append("- 无")
    lines.append(f"\n自选文件：{snapshot['data_files']['watchlist']}")
    return "\n".join(lines)


def _ensure_watchlist_file() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if WATCHLIST_PATH.exists():
        return
    template = TEMPLATE_DIR / "cash_watchlist.csv"
    if template.exists():
        WATCHLIST_PATH.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        WATCHLIST_PATH.write_text(_csv_header() + "\n", encoding="utf-8")


def _write_cash_watchlist(items: list[CashWatchItem]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with WATCHLIST_PATH.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "symbol",
                "name",
                "market",
                "category",
                "priority",
                "watch_reason",
                "trigger_condition",
                "status",
                "last_review_at",
                "notes",
            ],
        )
        writer.writeheader()
        for item in items:
            writer.writerow(asdict(item))


def _csv_header() -> str:
    return "symbol,name,market,category,priority,watch_reason,trigger_condition,status,last_review_at,notes"


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def _required_symbol(symbol: str) -> str:
    clean = symbol.strip().upper()
    if not clean:
        raise ValueError("自选股代码不能为空。")
    return clean


def _normalize_market(market: str | None) -> str:
    clean = (market or "").strip().upper()
    if clean in {"A", "A股", "CN", "CHINA", "ASHARE", "A_SHARE"}:
        return "CN"
    if clean in {"US", "USA", "美股"}:
        return "US"
    return clean or "CN"


def _count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "unknown")
        result[value] = result.get(value, 0) + 1
    return result
