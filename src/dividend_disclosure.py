"""境内红利持仓的财报分红检查流程。"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from datetime import date
from typing import Any

from src.portfolio_ledger import Holding, PortfolioEvent, read_holdings, read_portfolio_events


@dataclass(frozen=True)
class DividendHolding:
    """合并后的境内红利持仓。"""

    symbol: str
    name: str
    currency: str
    shares: float
    source_rows: tuple[str, ...]


@dataclass(frozen=True)
class FinancialReportReviewItem:
    """A 股红利持仓的财报核验待办。"""

    symbol: str
    name: str
    shares: float
    current_annual_dividend_per_share: float
    latest_dividend_event_date: str
    priority: str
    reason: str
    required_evidence: tuple[str, ...]
    next_action: str


def build_cn_dividend_disclosure_review(
    *,
    as_of: date | None = None,
    holdings: list[Holding] | None = None,
    events: list[PortfolioEvent] | None = None,
    search_announcements: bool | None = None,
    limit_per_symbol: int | None = None,
) -> dict[str, Any]:
    """生成境内红利持仓的财报口径分红核验清单。"""

    current_date = as_of or date.today()
    source_holdings = holdings if holdings is not None else read_holdings()
    source_events = events if events is not None else read_portfolio_events()
    dividend_holdings = list_cn_dividend_holdings(source_holdings)
    review_items = build_financial_report_review_items(
        source_holdings,
        source_events,
        as_of=current_date,
    )

    return {
        "status": "manual_financial_report_review_required" if review_items else "ok",
        "as_of": current_date.isoformat(),
        "scope": "境内红利持仓",
        "source_policy": {
            "accepted_sources": [
                "企业年报、半年报或季报中的利润分配方案",
                "企业同批披露的利润分配公告",
                "企业披露的权益分派实施公告",
            ],
            "rejected_sources": [
                "行情源返回的股息字段",
                "第三方股息率估算",
                "凭记忆或历史经验估算的分红",
            ],
        },
        "daily_review_step": (
            "每天复盘境内红利持仓时，先生成财报核验队列；只在确认企业财报、利润分配公告"
            "或权益分派实施公告后，才允许更新每股年分红或记录到账分红。"
        ),
        "provider": {
            "name": "本地财报核验工作流",
            "status": "manual_review",
            "error": "",
            "note": "当前未接入自动财报/公告检索源；定时任务不调用问财，也不使用行情源股息字段。",
        },
        "holding_count": len(dividend_holdings),
        "holdings": [asdict(item) for item in dividend_holdings],
        "announcement_results": [],
        "financial_report_review_items": [asdict(item) for item in review_items],
        "review_item_count": len(review_items),
        "warnings": [
            "当前未接入自动财报/公告数据源，本任务只生成核验清单和操作边界。",
            "现金流分红数据必须由财报、利润分配公告、权益分派实施公告或实际到账流水确认。",
        ],
    }


def review_cn_dividend_disclosures(*, chat_id: str | None = None) -> str:
    """返回可发送给用户的境内红利分红检查摘要。"""

    snapshot = build_cn_dividend_disclosure_review()
    return format_cn_dividend_disclosure_review(snapshot)


def format_cn_dividend_disclosure_review(snapshot: dict[str, Any]) -> str:
    """把检查结果压成飞书里可读的短消息。"""

    holding_count = int(snapshot.get("holding_count") or 0)
    review_items = snapshot.get("financial_report_review_items") or []
    high_priority = [item for item in review_items if item.get("priority") == "high"]
    lines = [
        "境内红利财报核验",
        f"我已把范围锁定在 {holding_count} 只 A 股红利持仓，只认企业财报和正式分配公告。",
        "当前未接入自动财报/公告检索源，本次不会调用问财，也不会使用行情源股息字段。",
    ]

    if not review_items:
        lines.append("本次没有生成待核验项；若后续披露年报、半年报或权益分派实施公告，再人工核验并更新账本。")
        return "\n".join(lines)

    lines.append(f"待核验项 {len(review_items)} 个，其中高优先级 {len(high_priority)} 个。")
    for item in review_items[:8]:
        symbol = str(item.get("symbol") or "")
        name = str(item.get("name") or "")
        reason = str(item.get("reason") or "")
        lines.append(f"- {symbol} {name}：{reason}")
    lines.append("核验后再用 /holding 更新每股年分红，或用 /dividend 记录实际到账现金分红。")
    return "\n".join(lines)


def list_cn_dividend_holdings(holdings: list[Holding] | None = None) -> list[DividendHolding]:
    """合并 A 股持仓中的带后缀和不带后缀重复行。"""

    grouped: dict[str, dict[str, Any]] = {}
    source_holdings = holdings if holdings is not None else read_holdings()
    for item in source_holdings:
        if not _is_cn_equity(item):
            continue
        symbol = canonical_cn_symbol(item.symbol)
        if not symbol:
            continue
        row = grouped.setdefault(
            symbol,
            {
                "symbol": symbol,
                "name": item.name,
                "currency": item.currency,
                "shares": 0.0,
                "source_rows": [],
            },
        )
        row["shares"] += item.shares
        row["source_rows"].append(item.symbol)
        if not row["name"] and item.name:
            row["name"] = item.name

    return [
        DividendHolding(
            symbol=str(row["symbol"]),
            name=str(row["name"]),
            currency=str(row["currency"]),
            shares=round(float(row["shares"]), 4),
            source_rows=tuple(str(item) for item in row["source_rows"]),
        )
        for row in sorted(grouped.values(), key=lambda item: str(item["symbol"]))
    ]


def canonical_cn_symbol(symbol: str) -> str:
    match = re.search(r"(\d{6})", symbol or "")
    return match.group(1) if match else ""


def build_financial_report_review_items(
    holdings: list[Holding] | None = None,
    events: list[PortfolioEvent] | None = None,
    *,
    as_of: date | None = None,
) -> list[FinancialReportReviewItem]:
    """Build manual review items that require financial-report evidence."""

    current_date = as_of or date.today()
    source_holdings = holdings if holdings is not None else read_holdings()
    source_events = events if events is not None else read_portfolio_events()
    latest_dividend_events = _latest_dividend_event_dates(source_events)
    items: list[FinancialReportReviewItem] = []
    for holding in _merged_active_cn_holding_rows(source_holdings):
        symbol = str(holding["symbol"])
        latest_event_date = latest_dividend_events.get(symbol, "")
        annual_dividend = float(holding["annual_dividend_per_share"] or 0)
        if annual_dividend <= 0:
            priority = "high"
            reason = "持仓账本缺少经财报或利润分配公告核验的每股年分红。"
        elif not latest_event_date or _parse_year(latest_event_date) < current_date.year:
            priority = "medium"
            reason = "今年尚未记录该持仓的现金分红到账流水，需核对最新财报或权益分派实施公告。"
        else:
            priority = "low"
            reason = "已有每股年分红和当年到账记录，仍需在新财报披露后例行复核。"
        items.append(
            FinancialReportReviewItem(
                symbol=symbol,
                name=str(holding["name"] or symbol),
                shares=round(float(holding["shares"] or 0), 4),
                current_annual_dividend_per_share=round(annual_dividend, 6),
                latest_dividend_event_date=latest_event_date,
                priority=priority,
                reason=reason,
                required_evidence=(
                    "年报、半年报或季报中的利润分配方案",
                    "同批披露的利润分配公告",
                    "权益分派实施公告",
                    "实际现金分红到账流水",
                ),
                next_action=(
                    "人工核验正式披露文件后，用 /holding 更新 annual_dividend_per_share，"
                    "或用 /dividend 记录到账现金分红。"
                ),
            )
        )
    return sorted(items, key=lambda item: (_priority_rank(item.priority), item.symbol))


def parse_cash_dividend_per_share(text: str) -> float | None:
    """从公告摘要里识别每股税前现金分红。"""

    compact = re.sub(r"\s+", "", text or "")
    patterns = [
        (r"每股(?:派发现金红利|现金分红|派发|派|分配|发放)?(?:人民币)?([0-9]+(?:\.[0-9]+)?)元", 1.0),
        (r"每10股(?:派发现金红利|现金分红|派发|派|分红[:：]?)(?:人民币)?([0-9]+(?:\.[0-9]+)?)元", 10.0),
        (r"10股派(?:发)?(?:现金红利)?([0-9]+(?:\.[0-9]+)?)元", 10.0),
        (r"10派([0-9]+(?:\.[0-9]+)?)", 10.0),
    ]
    for pattern, divisor in patterns:
        match = re.search(pattern, compact)
        if not match:
            continue
        return round(float(match.group(1)) / divisor, 6)
    return None


def _is_cn_equity(holding: Holding) -> bool:
    if holding.currency != "CNY":
        return False
    return holding.market == "A股" or bool(canonical_cn_symbol(holding.symbol))


def _active_cn_holdings(holdings: list[Holding]) -> list[Holding]:
    return [item for item in holdings if item.shares > 0 and _is_cn_equity(item)]


def _merged_active_cn_holding_rows(holdings: list[Holding]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for holding in _active_cn_holdings(holdings):
        symbol = canonical_cn_symbol(holding.symbol)
        if not symbol:
            continue
        row = grouped.setdefault(
            symbol,
            {
                "symbol": symbol,
                "name": holding.name,
                "shares": 0.0,
                "annual_dividend_per_share": 0.0,
            },
        )
        row["shares"] += holding.shares
        row["annual_dividend_per_share"] = max(
            float(row["annual_dividend_per_share"] or 0),
            float(holding.annual_dividend_per_share or 0),
        )
        if not row["name"] and holding.name:
            row["name"] = holding.name
    return sorted(grouped.values(), key=lambda item: str(item["symbol"]))


def _latest_dividend_event_dates(events: list[PortfolioEvent]) -> dict[str, str]:
    latest: dict[str, str] = {}
    for event in events:
        if event.event_type != "dividend":
            continue
        symbol = canonical_cn_symbol(event.symbol)
        if not symbol:
            continue
        if event.date > latest.get(symbol, ""):
            latest[symbol] = event.date
    return latest


def _parse_year(value: str) -> int:
    try:
        return int(str(value)[:4])
    except (TypeError, ValueError):
        return 0


def _priority_rank(priority: str) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get(priority, 9)
