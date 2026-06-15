"""境内红利持仓的财报分红检查流程。"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from datetime import date
from typing import Any

from src.market_intel import fetch_filings
from src.portfolio_ledger import Holding, PortfolioEvent, read_holdings, read_portfolio_events


CANDIDATE_TYPE_LABELS = {
    "financial_report": "财报候选",
    "profit_distribution": "利润分配候选",
    "equity_distribution_implementation": "权益分派实施候选",
    "other": "其他公告候选",
}


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
    should_search_announcements = True if search_announcements is None else bool(search_announcements)
    announcement_results = (
        fetch_dividend_filing_candidates(review_items, limit_per_symbol=limit_per_symbol or 3)
        if should_search_announcements
        else []
    )
    matched_announcement_count = sum(1 for item in announcement_results if item.get("candidate_count"))

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
            "name": "market_intel 财报/公告核验",
            "status": _announcement_provider_status(announcement_results),
            "error": "",
            "note": "定时任务基于财报、利润分配公告和权益分派实施公告生成候选核验项，不使用行情源股息字段作为现金流事实。",
        },
        "holding_count": len(dividend_holdings),
        "holdings": [asdict(item) for item in dividend_holdings],
        "announcement_results": announcement_results,
        "matched_announcement_count": matched_announcement_count,
        "financial_report_review_items": [asdict(item) for item in review_items],
        "review_item_count": len(review_items),
        "warnings": [
            "公告候选项只作为核验入口，更新账本前仍需人工打开正式披露文件确认。",
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
    announcement_results = snapshot.get("announcement_results") or []
    matched_announcement_count = int(snapshot.get("matched_announcement_count") or 0)
    high_priority = [item for item in review_items if item.get("priority") == "high"]
    lines = [
        "境内红利财报核验",
        f"我已把范围锁定在 {holding_count} 只 A 股红利持仓，只认企业财报和正式分配公告。",
        "本次基于财报、利润分配公告和权益分派实施公告生成核验队列，不使用行情源股息字段。",
    ]
    if announcement_results:
        lines.append(f"公告候选：{matched_announcement_count}/{len(announcement_results)} 只持仓返回候选披露。")
        category_totals = _aggregate_candidate_counts(announcement_results)
        lines.append(
            "公告拆分："
            f"财报候选 {category_totals.get('financial_report', 0)}，"
            f"利润分配候选 {category_totals.get('profit_distribution', 0)}，"
            f"权益分派实施候选 {category_totals.get('equity_distribution_implementation', 0)}。"
        )
        for result in announcement_results[:5]:
            symbol = str(result.get("symbol") or "")
            name = str(result.get("name") or "")
            candidates = result.get("candidates") or []
            if candidates:
                counts = result.get("classified_candidate_counts") or {}
                dividend_values = result.get("recognized_cash_dividend_per_share") or []
                dividend_text = (
                    "；可识别每股分红 " + ", ".join(str(value) for value in dividend_values[:3])
                    if dividend_values
                    else ""
                )
                lines.append(
                    f"- {symbol} {name}："
                    f"财报 {counts.get('financial_report', 0)}，"
                    f"利润分配 {counts.get('profit_distribution', 0)}，"
                    f"权益分派实施 {counts.get('equity_distribution_implementation', 0)}"
                    f"{dividend_text}"
                )
            else:
                coverage = (result.get("data_quality") or {}).get("coverage") or {}
                error = str(result.get("error") or "")
                lines.append(f"- {symbol} {name}：公告候选缺口 {coverage.get('filing', 'missing')} {error[:80]}")

        ledger_suggestions = _collect_ledger_update_suggestions(announcement_results)
        if ledger_suggestions:
            lines.append("账本更新建议（需人工确认）：")
            for suggestion in ledger_suggestions[:6]:
                if suggestion.get("action") == "record_dividend_cash_event":
                    lines.append(
                        f"- {suggestion.get('symbol')}：核验到账后可记录现金分红，"
                        f"税前估算 {suggestion.get('suggested_gross_amount')} {suggestion.get('currency')}。"
                    )
                else:
                    lines.append(
                        f"- {suggestion.get('symbol')}：核验后可把每股年分红更新为 "
                        f"{suggestion.get('suggested_value')} {suggestion.get('currency')}。"
                    )

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


def fetch_dividend_filing_candidates(
    review_items: list[FinancialReportReviewItem],
    *,
    limit_per_symbol: int = 3,
    days: int = 30,
) -> list[dict[str, Any]]:
    """Fetch formal filing candidates for dividend review items."""

    results: list[dict[str, Any]] = []
    for item in review_items:
        query = f"{item.symbol} {item.name} 财报 分红 利润分配 权益分派 实施公告"
        payload = fetch_filings(
            item.symbol,
            market="CN",
            query=query,
            limit=limit_per_symbol,
            days=days,
        )
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        candidates = [_normalize_dividend_filing_candidate(row) for row in data.get("items") or [] if isinstance(row, dict)]
        grouped_candidates = _group_dividend_candidates(candidates)
        results.append(
            {
                "symbol": item.symbol,
                "name": item.name,
                "status": payload.get("status"),
                "source": payload.get("source"),
                "data_quality": payload.get("data_quality") or {},
                "source_chain": payload.get("source_chain") or [],
                "error": payload.get("error") or "",
                "candidate_count": len(candidates),
                "candidates": candidates,
                "classified_candidate_counts": {
                    candidate_type: len(grouped_candidates.get(candidate_type, []))
                    for candidate_type in CANDIDATE_TYPE_LABELS
                },
                "financial_report_candidates": grouped_candidates.get("financial_report", []),
                "profit_distribution_candidates": grouped_candidates.get("profit_distribution", []),
                "equity_distribution_implementation_candidates": grouped_candidates.get(
                    "equity_distribution_implementation",
                    [],
                ),
                "recognized_cash_dividend_per_share": _recognized_cash_dividend_values(candidates),
                "ledger_update_suggestions": _build_ledger_update_suggestions(item, candidates),
            }
        )
    return results


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


def _normalize_dividend_filing_candidate(row: dict[str, Any]) -> dict[str, Any]:
    title = str(row.get("title") or "")
    summary = str(row.get("summary") or "")
    category = str(row.get("category") or "")
    text = " ".join(item for item in [title, summary, category] if item)
    candidate_types = classify_dividend_candidate_types(text)
    primary_type = candidate_types[0]
    return {
        "symbol": row.get("symbol"),
        "name": row.get("name"),
        "title": title,
        "summary": summary[:240],
        "category": category,
        "published_at": row.get("published_at"),
        "url": row.get("url"),
        "source": row.get("source"),
        "provider": row.get("provider"),
        "candidate_type": primary_type,
        "candidate_type_label": CANDIDATE_TYPE_LABELS.get(primary_type, primary_type),
        "candidate_types": candidate_types,
        "cash_dividend_per_share": parse_cash_dividend_per_share(text),
        "distribution_dates": parse_distribution_dates(text),
    }


def classify_dividend_candidate_types(text: str) -> list[str]:
    """Classify formal disclosures for the CN dividend review workflow."""

    clean = re.sub(r"\s+", "", text or "")
    checks = [
        (
            "equity_distribution_implementation",
            ["权益分派实施", "实施公告", "股权登记日", "除权除息", "现金红利发放日", "派息日"],
        ),
        (
            "profit_distribution",
            ["利润分配", "分红", "现金红利", "10派", "每10股派", "每股派", "派息"],
        ),
        (
            "financial_report",
            ["年度报告", "年报", "半年度报告", "半年报", "季度报告", "一季报", "三季报", "财务报告", "定期报告"],
        ),
    ]
    result = [candidate_type for candidate_type, tokens in checks if any(token in clean for token in tokens)]
    return result or ["other"]


def parse_distribution_dates(text: str) -> dict[str, str]:
    """Extract raw distribution dates from implementation announcement text."""

    clean = re.sub(r"\s+", "", text or "")
    date_pattern = r"([0-9]{4}年[0-9]{1,2}月[0-9]{1,2}日|[0-9]{4}-[0-9]{1,2}-[0-9]{1,2})"
    patterns = {
        "record_date": rf"股权登记日[:：]?{date_pattern}",
        "ex_dividend_date": rf"(?:除权除息日|除息日)[:：]?{date_pattern}",
        "cash_payment_date": rf"(?:现金红利发放日|红利发放日|派息日)[:：]?{date_pattern}",
    }
    result: dict[str, str] = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, clean)
        if match:
            result[key] = match.group(1)
    return result


def _group_dividend_candidates(candidates: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {candidate_type: [] for candidate_type in CANDIDATE_TYPE_LABELS}
    for candidate in candidates:
        candidate_types = candidate.get("candidate_types") if isinstance(candidate.get("candidate_types"), list) else []
        for candidate_type in candidate_types or [candidate.get("candidate_type") or "other"]:
            key = str(candidate_type or "other")
            grouped.setdefault(key, []).append(candidate)
    return grouped


def _recognized_cash_dividend_values(candidates: list[dict[str, Any]]) -> list[float]:
    values: list[float] = []
    for candidate in candidates:
        value = candidate.get("cash_dividend_per_share")
        if value is None:
            continue
        clean = round(float(value), 6)
        if clean not in values:
            values.append(clean)
    return values


def _build_ledger_update_suggestions(
    item: FinancialReportReviewItem,
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    seen: set[tuple[str, float]] = set()
    for candidate in candidates:
        value = candidate.get("cash_dividend_per_share")
        if value is None:
            continue
        amount_per_share = round(float(value), 6)
        candidate_types = {
            str(candidate_type)
            for candidate_type in candidate.get("candidate_types", [])
            if str(candidate_type)
        }
        if not candidate_types:
            candidate_types = {str(candidate.get("candidate_type") or "other")}
        if candidate_types & {"profit_distribution", "financial_report"}:
            key = ("update_holding_annual_dividend_per_share", amount_per_share)
            if key not in seen:
                seen.add(key)
                suggestions.append(
                    {
                        "action": "update_holding_annual_dividend_per_share",
                        "symbol": item.symbol,
                        "field": "annual_dividend_per_share",
                        "current_value": item.current_annual_dividend_per_share,
                        "suggested_value": amount_per_share,
                        "currency": "CNY",
                        "source_title": candidate.get("title") or "",
                        "source_url": candidate.get("url") or "",
                        "confirmation_required": True,
                        "reason": "候选公告可识别每股现金分红，需人工核验正式披露后再更新持仓账本。",
                        "command_hint": f"/holding {item.symbol} <shares> <cost_price> dividend={amount_per_share}",
                    }
                )
        if "equity_distribution_implementation" in candidate_types:
            gross_amount = round(item.shares * amount_per_share, 2)
            key = ("record_dividend_cash_event", amount_per_share)
            if key not in seen:
                seen.add(key)
                distribution_dates = (
                    candidate.get("distribution_dates")
                    if isinstance(candidate.get("distribution_dates"), dict)
                    else {}
                )
                cash_payment_date = str(distribution_dates.get("cash_payment_date") or "<到账日>")
                suggestions.append(
                    {
                        "action": "record_dividend_cash_event",
                        "symbol": item.symbol,
                        "field": "portfolio_events",
                        "shares": item.shares,
                        "cash_dividend_per_share": amount_per_share,
                        "suggested_gross_amount": gross_amount,
                        "currency": "CNY",
                        "cash_payment_date": cash_payment_date,
                        "source_title": candidate.get("title") or "",
                        "source_url": candidate.get("url") or "",
                        "confirmation_required": True,
                        "reason": "权益分派实施候选可估算税前到账金额，需与券商流水和税费确认后再入账。",
                        "command_hint": (
                            f"/dividend symbol={item.symbol} amount={gross_amount} "
                            f"date={cash_payment_date} notes=权益分派实施公告人工确认"
                        ),
                    }
                )
    return suggestions[:5]


def _aggregate_candidate_counts(results: list[dict[str, Any]]) -> dict[str, int]:
    totals = {candidate_type: 0 for candidate_type in CANDIDATE_TYPE_LABELS}
    for result in results:
        counts = result.get("classified_candidate_counts") if isinstance(result.get("classified_candidate_counts"), dict) else {}
        for candidate_type in totals:
            totals[candidate_type] += int(counts.get(candidate_type) or 0)
    return totals


def _collect_ledger_update_suggestions(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    for result in results:
        for suggestion in result.get("ledger_update_suggestions") or []:
            if isinstance(suggestion, dict):
                suggestions.append(suggestion)
    return suggestions


def _announcement_provider_status(results: list[dict[str, Any]]) -> str:
    if not results:
        return "not_requested"
    if any(item.get("candidate_count") for item in results):
        return "ok"
    statuses = {str(item.get("status") or "") for item in results}
    if statuses == {"provider_not_configured"}:
        return "provider_not_configured"
    if "error" in statuses:
        return "error"
    return "empty"


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
