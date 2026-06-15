"""Growth_Engine legacy local snapshot and review workflow."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

from src.init import FRAMEWORKS_DIR
from src.llm_client import LLMClient
from src.prompts import growth_review_system_prompt, growth_review_user_prompt


GROWTH_DIR = FRAMEWORKS_DIR / "Growth_Engine"
DATA_DIR = GROWTH_DIR / "data"
TEMPLATE_DIR = GROWTH_DIR / "data_templates"
HOLDINGS_PATH = DATA_DIR / "growth_holdings.csv"
WATCHLIST_PATH = DATA_DIR / "growth_watchlist.csv"

VALID_MARKETS = {"US"}
MARKET_TO_SUB_FRAMEWORK = {
    "US": "US_Disruptive_Growth",
}


@dataclass(frozen=True)
class GrowthHolding:
    symbol: str
    name: str
    market: str
    sub_framework: str
    shares: float
    cost_price: float
    current_price: float
    position_type: str
    thesis: str
    status: str
    last_review_at: str = ""
    notes: str = ""


@dataclass(frozen=True)
class GrowthWatchItem:
    symbol: str
    name: str
    market: str
    sub_framework: str
    priority: str
    watch_reason: str
    trigger_condition: str
    status: str
    last_review_at: str = ""
    notes: str = ""


def upsert_growth_holding(
    *,
    symbol: str,
    name: str = "",
    market: str = "",
    sub_framework: str = "",
    shares: float,
    cost_price: float,
    current_price: float,
    position_type: str = "核心仓",
    thesis: str = "",
    status: str = "active",
    last_review_at: str = "",
    notes: str = "",
) -> dict[str, Any]:
    """Create or update one Growth_Engine holding."""

    clean_symbol = _required_symbol(symbol)
    clean_market = _normalize_market(market or _infer_market(clean_symbol))
    clean_sub_framework = sub_framework or MARKET_TO_SUB_FRAMEWORK.get(clean_market, "Growth_Engine")
    if shares < 0 or cost_price < 0 or current_price < 0:
        raise ValueError("shares、cost_price、current_price 不能为负数。")

    _ensure_growth_data_files()
    current = GrowthHolding(
        symbol=clean_symbol,
        name=name or clean_symbol,
        market=clean_market,
        sub_framework=clean_sub_framework,
        shares=shares,
        cost_price=cost_price,
        current_price=current_price,
        position_type=position_type,
        thesis=thesis,
        status=status,
        last_review_at=last_review_at,
        notes=notes,
    )

    rows = read_growth_holdings()
    replaced = False
    next_rows: list[GrowthHolding] = []
    for item in rows:
        if item.symbol.upper() == clean_symbol.upper():
            next_rows.append(current)
            replaced = True
        else:
            next_rows.append(item)
    if not replaced:
        next_rows.append(current)
    _write_growth_holdings(next_rows)
    snapshot = build_growth_snapshot()
    snapshot["updated_holding"] = asdict(current)
    snapshot["holding_action"] = "updated" if replaced else "created"
    return snapshot


def upsert_growth_watch_item(
    *,
    symbol: str,
    name: str = "",
    market: str = "",
    sub_framework: str = "",
    priority: str = "medium",
    watch_reason: str = "",
    trigger_condition: str = "",
    status: str = "active",
    last_review_at: str = "",
    notes: str = "",
) -> dict[str, Any]:
    """Create or update one Growth_Engine watchlist item."""

    clean_symbol = _required_symbol(symbol)
    clean_market = _normalize_market(market or _infer_market(clean_symbol))
    clean_sub_framework = sub_framework or MARKET_TO_SUB_FRAMEWORK.get(clean_market, "Growth_Engine")
    _ensure_growth_data_files()
    current = GrowthWatchItem(
        symbol=clean_symbol,
        name=name or clean_symbol,
        market=clean_market,
        sub_framework=clean_sub_framework,
        priority=priority,
        watch_reason=watch_reason,
        trigger_condition=trigger_condition,
        status=status,
        last_review_at=last_review_at,
        notes=notes,
    )
    rows = read_growth_watchlist()
    replaced = False
    next_rows: list[GrowthWatchItem] = []
    for item in rows:
        if item.symbol.upper() == clean_symbol.upper():
            next_rows.append(current)
            replaced = True
        else:
            next_rows.append(item)
    if not replaced:
        next_rows.append(current)
    _write_growth_watchlist(next_rows)
    snapshot = build_growth_snapshot()
    snapshot["updated_watch_item"] = asdict(current)
    snapshot["watch_action"] = "updated" if replaced else "created"
    return snapshot


def build_growth_snapshot(market: str | None = None, symbol: str | None = None) -> dict[str, Any]:
    """Build deterministic Growth_Engine local portfolio snapshot."""

    _ensure_growth_data_files()
    market_filter = _normalize_market(market) if market else None
    symbol_filter = symbol.upper() if symbol else None
    holdings = [
        item
        for item in read_growth_holdings()
        if (not market_filter or item.market == market_filter)
        and (not symbol_filter or item.symbol.upper() == symbol_filter)
    ]
    watchlist = [
        item
        for item in read_growth_watchlist()
        if (not market_filter or item.market == market_filter)
        and (not symbol_filter or item.symbol.upper() == symbol_filter)
    ]
    positions = [_holding_metrics(item) for item in holdings]
    total_cost = sum(item["cost_basis"] for item in positions)
    total_market_value = sum(item["market_value"] for item in positions)
    return {
        "as_of": date.today().isoformat(),
        "market_filter": market_filter or "",
        "symbol_filter": symbol_filter or "",
        "data_files": {
            "holdings": str(HOLDINGS_PATH),
            "watchlist": str(WATCHLIST_PATH),
        },
        "missing_files": _missing_data_files(),
        "summary": {
            "holding_count": len(holdings),
            "watchlist_count": len(watchlist),
            "total_cost": round(total_cost, 2),
            "total_market_value": round(total_market_value, 2),
            "unrealized_pnl": round(total_market_value - total_cost, 2),
            "unrealized_pnl_pct": _safe_ratio(total_market_value - total_cost, total_cost),
            "by_market": _count_by(positions, "market"),
            "by_sub_framework": _count_by(positions, "sub_framework"),
        },
        "holdings": positions,
        "watchlist": [asdict(item) for item in watchlist],
        "template_files": {
            "holdings": str(TEMPLATE_DIR / "growth_holdings.csv"),
            "watchlist": str(TEMPLATE_DIR / "growth_watchlist.csv"),
        },
    }


def review_growth_symbol(symbol: str, chat_id: str | None = None) -> str:
    """Run LLM review for one Growth_Engine symbol using local data."""

    clean_symbol = _required_symbol(symbol)
    snapshot = build_growth_snapshot(symbol=clean_symbol)
    if not snapshot["holdings"] and not snapshot["watchlist"]:
        return (
            f"未在 Growth_Engine 本地持仓或自选中找到：{clean_symbol}\n"
            "Growth Engine 的正式标的来源已经改为长桥 universe，请先确认长桥持仓或自选股。"
        )
    snapshot = enrich_growth_snapshot_with_market_data(snapshot)
    return _run_growth_review_llm(
        review_type="single_symbol",
        market=snapshot["holdings"][0]["market"] if snapshot["holdings"] else snapshot["watchlist"][0]["market"],
        symbol=clean_symbol,
        snapshot=snapshot,
        chat_id=chat_id,
    )


def review_growth_daily(market: str, chat_id: str | None = None) -> str:
    """Run daily holdings/watchlist review for one market."""

    clean_market = _normalize_market(market)
    snapshot = build_growth_snapshot(market=clean_market)
    if not snapshot["holdings"] and not snapshot["watchlist"]:
        return f"Growth_Engine {clean_market} 复盘未执行：本地持仓和自选列表均为空。"
    snapshot = enrich_growth_snapshot_with_market_data(snapshot)
    return _run_growth_review_llm(
        review_type="daily_market_review",
        market=clean_market,
        symbol="",
        snapshot=snapshot,
        chat_id=chat_id,
    )


def format_growth_snapshot(snapshot: dict[str, Any]) -> str:
    summary = snapshot["summary"]
    lines = [
        "Growth_Engine 本地快照：",
        f"- 日期：{snapshot['as_of']}",
        f"- 市场过滤：{snapshot['market_filter'] or '全部'}",
        f"- 持仓数：{summary['holding_count']}",
        f"- 自选数：{summary['watchlist_count']}",
        f"- 总成本：{summary['total_cost']:,.2f}",
        f"- 当前市值：{summary['total_market_value']:,.2f}",
        f"- 未实现盈亏：{summary['unrealized_pnl']:,.2f} ({summary['unrealized_pnl_pct']:.2%})",
        "",
        "持仓：",
    ]
    if snapshot["holdings"]:
        for item in snapshot["holdings"]:
            lines.append(
                f"- {item['symbol']} {item['name']}：{item['shares']:,.2f} 股，"
                f"成本 {item['cost_price']:,.4f}，现价 {item['current_price']:,.4f}，"
                f"盈亏 {item['unrealized_pnl_pct']:.2%}"
            )
    else:
        lines.append("- 无")
    lines.extend(["", f"持仓文件：{snapshot['data_files']['holdings']}", f"自选文件：{snapshot['data_files']['watchlist']}"])
    return "\n".join(lines)


def enrich_growth_snapshot_with_market_data(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Attach read-only market data to a Growth snapshot before LLM review."""

    from src.market_data import fetch_market_data

    symbols: dict[str, str] = {}
    for item in snapshot.get("holdings", []):
        symbols[str(item.get("symbol") or "")] = str(item.get("market") or "")
    for item in snapshot.get("watchlist", []):
        symbols[str(item.get("symbol") or "")] = str(item.get("market") or "")

    market_data: dict[str, Any] = {}
    for symbol, market in symbols.items():
        if not symbol:
            continue
        market_data[symbol] = fetch_market_data(symbol, market=market)

    enriched = dict(snapshot)
    enriched["market_data"] = market_data
    enriched["market_data_policy"] = {
        "source_rule": "US uses Longbridge.",
        "failure_policy": "If status is error, treat current quote/dividend as missing and state the data gap.",
    }
    return enriched


def read_growth_holdings() -> list[GrowthHolding]:
    if not HOLDINGS_PATH.exists():
        return []
    rows = _read_csv(HOLDINGS_PATH)
    return [
        GrowthHolding(
            symbol=str(row.get("symbol") or "").strip(),
            name=str(row.get("name") or "").strip(),
            market=_normalize_market(str(row.get("market") or "")),
            sub_framework=str(row.get("sub_framework") or "").strip(),
            shares=_to_float(row.get("shares")),
            cost_price=_to_float(row.get("cost_price")),
            current_price=_to_float(row.get("current_price")),
            position_type=str(row.get("position_type") or "").strip(),
            thesis=str(row.get("thesis") or "").strip(),
            status=str(row.get("status") or "active").strip(),
            last_review_at=str(row.get("last_review_at") or "").strip(),
            notes=str(row.get("notes") or "").strip(),
        )
        for row in rows
        if str(row.get("symbol") or "").strip()
    ]


def read_growth_watchlist() -> list[GrowthWatchItem]:
    if not WATCHLIST_PATH.exists():
        return []
    rows = _read_csv(WATCHLIST_PATH)
    return [
        GrowthWatchItem(
            symbol=str(row.get("symbol") or "").strip(),
            name=str(row.get("name") or "").strip(),
            market=_normalize_market(str(row.get("market") or "")),
            sub_framework=str(row.get("sub_framework") or "").strip(),
            priority=str(row.get("priority") or "").strip(),
            watch_reason=str(row.get("watch_reason") or "").strip(),
            trigger_condition=str(row.get("trigger_condition") or "").strip(),
            status=str(row.get("status") or "active").strip(),
            last_review_at=str(row.get("last_review_at") or "").strip(),
            notes=str(row.get("notes") or "").strip(),
        )
        for row in rows
        if str(row.get("symbol") or "").strip()
    ]


def _run_growth_review_llm(
    *,
    review_type: str,
    market: str,
    symbol: str,
    snapshot: dict[str, Any],
    chat_id: str | None,
) -> str:
    sub_framework = MARKET_TO_SUB_FRAMEWORK.get(market, "Growth_Engine")
    strategy_context = _load_growth_context(sub_framework)
    client = LLMClient.for_framework("Growth_Engine")
    return client.complete(
        system_prompt=growth_review_system_prompt(),
        user_prompt=growth_review_user_prompt(
            review_type=review_type,
            market=market,
            symbol=symbol,
            strategy_context=strategy_context,
            snapshot_json=json.dumps(snapshot, ensure_ascii=False, indent=2),
        ),
        agent_role="growth_reviewer",
        call_site="growth_portfolio.review",
        framework_id="Growth_Engine",
        context_bundle_id=sub_framework,
        chat_id=chat_id,
        user_query=f"{review_type}:{market}:{symbol}",
    )


def _load_growth_context(sub_framework: str) -> str:
    files = [GROWTH_DIR / "constitution.md"]
    if sub_framework == "US_Disruptive_Growth":
        files.append(GROWTH_DIR / "sub_frameworks" / f"{sub_framework}.md")
    return "\n\n---\n\n".join(f"# 来源：{path}\n\n{path.read_text(encoding='utf-8')}" for path in files)


def _ensure_growth_data_files() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not HOLDINGS_PATH.exists():
        HOLDINGS_PATH.write_text((TEMPLATE_DIR / "growth_holdings.csv").read_text(encoding="utf-8") + "\n", encoding="utf-8")
    if not WATCHLIST_PATH.exists():
        WATCHLIST_PATH.write_text((TEMPLATE_DIR / "growth_watchlist.csv").read_text(encoding="utf-8") + "\n", encoding="utf-8")


def _write_growth_holdings(holdings: list[GrowthHolding]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with HOLDINGS_PATH.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "symbol",
                "name",
                "market",
                "sub_framework",
                "shares",
                "cost_price",
                "current_price",
                "position_type",
                "thesis",
                "status",
                "last_review_at",
                "notes",
            ],
        )
        writer.writeheader()
        for item in holdings:
            row = asdict(item)
            for key in ["shares", "cost_price", "current_price"]:
                row[key] = _format_decimal(float(row[key]), 4)
            writer.writerow(row)


def _write_growth_watchlist(items: list[GrowthWatchItem]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with WATCHLIST_PATH.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "symbol",
                "name",
                "market",
                "sub_framework",
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


def _holding_metrics(holding: GrowthHolding) -> dict[str, Any]:
    cost_basis = holding.shares * holding.cost_price
    market_value = holding.shares * holding.current_price
    return {
        **asdict(holding),
        "cost_basis": round(cost_basis, 2),
        "market_value": round(market_value, 2),
        "unrealized_pnl": round(market_value - cost_basis, 2),
        "unrealized_pnl_pct": _safe_ratio(market_value - cost_basis, cost_basis),
    }


def _missing_data_files() -> list[str]:
    return [str(path) for path in [HOLDINGS_PATH, WATCHLIST_PATH] if not path.exists()]


def _count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "unknown")
        result[value] = result.get(value, 0) + 1
    return result


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def _required_symbol(symbol: str) -> str:
    clean = symbol.strip().upper()
    if not clean:
        raise ValueError("标的代码不能为空。")
    return clean


def _infer_market(symbol: str) -> str:
    upper = symbol.upper()
    if upper.endswith(".US"):
        return "US"
    raise ValueError("Growth_Engine 仅支持美股标的，请使用 .US 代码或长桥 universe。")


def _normalize_market(market: str | None) -> str:
    clean = (market or "").strip().upper()
    if clean in {"US", "USA", "美股"}:
        return "US"
    if not clean:
        return "US"
    raise ValueError("Growth_Engine 仅支持 US 市场。")


def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    text = str(value).strip().replace(",", "")
    if not text:
        return 0.0
    return float(text)


def _safe_ratio(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 6)


def _format_decimal(value: float, places: int) -> str:
    return f"{value:.{places}f}".rstrip("0").rstrip(".")
