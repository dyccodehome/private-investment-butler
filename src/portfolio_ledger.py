"""Cash_Anchor 本地持仓账本与退休分红进度计算。

本模块只做确定性读写和计算，不调用 LLM。它让现金流策略里的“分红能力、
成本股息率、年度投入进度、退休目标缺口”有可审计的数据来源。
"""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass, asdict, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from src.init import FRAMEWORKS_DIR


CASH_ANCHOR_DIR = FRAMEWORKS_DIR / "Cash_Anchor"
DATA_DIR = CASH_ANCHOR_DIR / "data"
TEMPLATE_DIR = CASH_ANCHOR_DIR / "data_templates"
HOLDINGS_PATH = DATA_DIR / "holdings.csv"
CAPITAL_FLOWS_PATH = DATA_DIR / "capital_flows.csv"
PORTFOLIO_EVENTS_PATH = DATA_DIR / "portfolio_events.csv"
DIVIDEND_PLAN_PATH = DATA_DIR / "dividend_plan.yaml"
US_DISTRIBUTION_HISTORY_PATH = DATA_DIR / "us_distribution_history.csv"
US_INCOME_SYMBOLS = {"QQQI", "QQQI.US", "XQQI", "XQQI.US", "TQQQ", "TQQQ.US"}
DEFAULT_INDUSTRY_LIMIT_PCT = {
    "bank": 0.30,
    "insurance": 0.15,
    "resource": 0.20,
    "utility": 0.30,
    "telecom": 0.20,
    "transport": 0.15,
    "consumer": 0.20,
}
DEFAULT_CYCLICAL_INDUSTRIES = ["resource", "coal", "shipping", "nonferrous"]
DEFAULT_SYMBOL_LIMIT_TYPES = {
    "000333": "normal",
    "600036": "core",
    "600132": "normal",
    "600795": "normal",
    "600887": "normal",
    "600900": "core",
    "600941": "core",
    "601166": "normal",
    "601318": "normal",
    "601985": "normal",
}
DEFAULT_SYMBOL_INDUSTRIES = {
    "000333": "consumer",
    "600036": "bank",
    "600132": "consumer",
    "600795": "utility",
    "600887": "consumer",
    "600900": "utility",
    "600941": "telecom",
    "601166": "bank",
    "601318": "insurance",
    "601985": "utility",
}
LIMIT_TYPE_LABELS = {
    "core": "超高确定性核心红利",
    "normal": "普通红利龙头",
    "cyclical": "强周期红利资产",
}
INDUSTRY_LABELS = {
    "bank": "银行",
    "insurance": "保险",
    "resource": "煤炭/资源",
    "coal": "煤炭",
    "shipping": "航运",
    "nonferrous": "有色",
    "utility": "电力/公用事业",
    "telecom": "运营商",
    "transport": "交运",
    "consumer": "消费红利",
    "unknown": "未分类",
}


@dataclass(frozen=True)
class Holding:
    """现金流策略持仓明细。"""

    symbol: str
    name: str
    market: str
    currency: str
    shares: float
    cost_price: float
    current_price: float
    annual_dividend_per_share: float
    tax_rate: float
    notes: str = ""


@dataclass(frozen=True)
class CapitalFlow:
    """年度工资投入或其他本金追加记录。"""

    date: str
    amount: float
    currency: str
    source: str
    notes: str = ""


@dataclass(frozen=True)
class PortfolioEvent:
    """持仓账本事件，记录买入、卖出、分红和人工快照。"""

    date: str
    event_type: str
    symbol: str
    shares: float
    price: float
    amount: float
    currency: str
    source: str
    notes: str = ""


@dataclass(frozen=True)
class USDistributionRecord:
    """美元收益基金历史每份分配记录。"""

    symbol: str
    ex_date: str
    payment_date: str
    record_date: str
    amount_per_share: float
    currency: str
    source: str
    notes: str = ""


@dataclass(frozen=True)
class DividendPlan:
    """现金流执行计划的核心参数。"""

    plan_name: str = "Cash Anchor 10 Year Retirement Plan"
    base_year: int = 2026
    retirement_years: int = 10
    annual_contribution_target: float = 0.0
    currency: str = "CNY"
    single_position_limit_pct: float = 0.10
    core_position_limit_pct: float = 0.15
    cyclical_position_limit_pct: float = 0.08
    cyclical_total_limit_pct: float = 0.25
    industry_limit_default_pct: float = 0.30
    industry_limit_pct: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_INDUSTRY_LIMIT_PCT))
    cyclical_industries: list[str] = field(default_factory=lambda: list(DEFAULT_CYCLICAL_INDUSTRIES))
    symbol_limit_types: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_SYMBOL_LIMIT_TYPES))
    symbol_industries: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_SYMBOL_INDUSTRIES))


def build_portfolio_snapshot(as_of: date | None = None) -> dict[str, Any]:
    """读取本地账本并返回现金流策略快照。"""

    current_date = as_of or date.today()
    holdings = read_holdings()
    flows = read_capital_flows()
    events = read_portfolio_events()
    plan = read_dividend_plan()
    positions = [_position_metrics(item) for item in holdings]

    total_cost = sum(item["cost_basis"] for item in positions)
    total_market_value = sum(item["market_value"] for item in positions)
    gross_annual_dividend = sum(item["gross_annual_dividend"] for item in positions)
    net_annual_dividend = sum(item["net_annual_dividend"] for item in positions)
    current_year_contribution = sum(
        flow.amount for flow in flows if _parse_year(flow.date) == current_date.year
    )
    dividend_analysis = _build_dividend_analysis(holdings, positions, events, current_date, plan.currency)
    currency_breakdown = _build_currency_breakdown(positions, flows, events, current_date)
    position_limit_analysis = _build_position_limit_analysis(positions, plan)

    return {
        "as_of": current_date.isoformat(),
        "data_files": {
            "holdings": str(HOLDINGS_PATH),
            "capital_flows": str(CAPITAL_FLOWS_PATH),
            "portfolio_events": str(PORTFOLIO_EVENTS_PATH),
            "dividend_plan": str(DIVIDEND_PLAN_PATH),
            "us_distribution_history": str(US_DISTRIBUTION_HISTORY_PATH),
        },
        "missing_files": _missing_data_files(),
        "plan": asdict(plan),
        "summary": {
            "holding_count": len(holdings),
            "total_cost": round(total_cost, 2),
            "total_market_value": round(total_market_value, 2),
            "gross_annual_dividend": round(gross_annual_dividend, 2),
            "net_annual_dividend": round(net_annual_dividend, 2),
            "yield_on_cost": _safe_ratio(gross_annual_dividend, total_cost),
            "current_yield": _safe_ratio(gross_annual_dividend, total_market_value),
            "net_yield_on_cost": _safe_ratio(net_annual_dividend, total_cost),
            "currency_scope": "mixed" if currency_breakdown["is_mixed_currency"] else plan.currency,
            "total_cost_by_currency": [
                {"currency": item["currency"], "amount": item["total_cost"]}
                for item in currency_breakdown["position_totals_by_currency"]
            ],
            "total_market_value_by_currency": [
                {"currency": item["currency"], "amount": item["total_market_value"]}
                for item in currency_breakdown["position_totals_by_currency"]
            ],
            "current_year_dividend_received": dividend_analysis["current_year_received"]["plan_currency_amount"],
            "current_year_dividend_received_by_currency": dividend_analysis["current_year_received"]["total_by_currency"],
            "current_year_contribution": round(current_year_contribution, 2),
            "annual_contribution_progress": _safe_ratio(
                current_year_contribution,
                plan.annual_contribution_target,
            ),
            "annual_contribution_gap": round(
                max(plan.annual_contribution_target - current_year_contribution, 0),
                2,
            ),
        },
        "dividend_analysis": dividend_analysis,
        "market_breakdown": _build_market_breakdown(positions),
        "currency_breakdown": currency_breakdown,
        "position_limit_analysis": position_limit_analysis,
        "data_quality": _data_quality_with_position_limits(
            _build_data_quality(holdings, events, current_date),
            position_limit_analysis,
        ),
        "positions": positions,
        "capital_flows": [asdict(item) for item in flows],
        "portfolio_events": [asdict(item) for item in events],
        "template_files": {
            "holdings": str(TEMPLATE_DIR / "holdings.csv"),
            "capital_flows": str(TEMPLATE_DIR / "capital_flows.csv"),
            "dividend_plan": str(TEMPLATE_DIR / "dividend_plan.yaml"),
        },
    }


def build_enriched_portfolio_snapshot(as_of: date | None = None) -> dict[str, Any]:
    """Build Cash Anchor snapshot with read-only market data for analysis."""

    from src.market_data import fetch_market_data

    snapshot = build_portfolio_snapshot(as_of=as_of)
    market_data: dict[str, Any] = {}
    for item in snapshot.get("positions", []):
        symbol = str(item.get("symbol") or "")
        if not symbol:
            continue
        market_data[symbol] = _market_data_for_portfolio_snapshot(
            fetch_market_data(symbol, market=str(item.get("market") or ""))
        )
    enriched = dict(snapshot)
    enriched["market_data"] = market_data
    enriched["market_data_summary"] = _build_market_data_summary(market_data)
    enriched["exchange_rates"] = _fetch_exchange_rates_for_snapshot(snapshot)
    valuation_positions = _positions_with_market_data(
        list(enriched.get("positions") or []),
        market_data,
    )
    position_limit_analysis = _build_position_limit_analysis(valuation_positions, read_dividend_plan())
    enriched["position_limit_analysis"] = position_limit_analysis
    if enriched["exchange_rates"].get("status") == "ok":
        dividend_analysis = dict(enriched.get("dividend_analysis") or {})
        dividend_analysis["portfolio_dividend_yield_estimate"] = _build_portfolio_dividend_yield_estimate(
            valuation_positions,
            dict(dividend_analysis.get("us_income_distribution_forecast") or {}),
            base_currency=str(enriched.get("plan", {}).get("currency") or "CNY"),
            fx_rates=list(enriched["exchange_rates"].get("rates") or []),
            fx_source=str(enriched["exchange_rates"].get("source") or ""),
        )
        enriched["dividend_analysis"] = dividend_analysis
    else:
        dividend_analysis = dict(enriched.get("dividend_analysis") or {})
        dividend_analysis["portfolio_dividend_yield_estimate"] = _build_portfolio_dividend_yield_estimate(
            valuation_positions,
            dict(dividend_analysis.get("us_income_distribution_forecast") or {}),
        )
        enriched["dividend_analysis"] = dividend_analysis
    enriched["market_data_policy"] = {
        "source_rule": "境内标的和美元标的分别走只读行情源。",
        "failure_policy": "行情错误只影响最新价、动态股息率和均线，不能覆盖分红到账流水，也不能否定持仓账本里已经核验过的每股年分红。",
        "cashflow_dividend_policy": (
            "现金流收入不能使用行情源返回的股息字段。分红预估只能来自人工核验后的持仓账本、分红到账流水，"
            "或企业财报、利润分配公告、权益分派实施公告等正式披露文件。"
        ),
        "write_policy": "分析期间只读，不自动覆盖持仓账本。",
    }
    enriched["data_quality"] = {
        **_data_quality_with_position_limits(dict(snapshot.get("data_quality") or {}), position_limit_analysis),
        "market_data": enriched["market_data_summary"],
    }
    return enriched


def record_capital_contribution(
    *,
    amount: float,
    contribution_date: date | None = None,
    currency: str = "CNY",
    source: str = "salary",
    notes: str = "",
) -> dict[str, Any]:
    """记录一次工资投入或本金追加，并返回年度进度。"""

    if amount <= 0:
        raise ValueError("投入金额必须大于 0。")

    target_date = contribution_date or date.today()
    _ensure_cash_anchor_data_files()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    file_exists = CAPITAL_FLOWS_PATH.exists()
    with CAPITAL_FLOWS_PATH.open("a", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["date", "amount", "currency", "source", "notes"])
        if not file_exists or CAPITAL_FLOWS_PATH.stat().st_size == 0:
            writer.writeheader()
        writer.writerow(
            {
                "date": target_date.isoformat(),
                "amount": _format_amount(amount),
                "currency": currency,
                "source": source,
                "notes": notes,
            }
        )

    snapshot = build_portfolio_snapshot(as_of=target_date)
    summary = snapshot["summary"]
    plan = snapshot["plan"]
    return {
        "date": target_date.isoformat(),
        "amount": amount,
        "currency": currency,
        "source": source,
        "notes": notes,
        "capital_flows_path": str(CAPITAL_FLOWS_PATH),
        "annual_contribution_target": plan["annual_contribution_target"],
        "current_year_contribution": summary["current_year_contribution"],
        "annual_contribution_gap": summary["annual_contribution_gap"],
        "annual_contribution_progress": summary["annual_contribution_progress"],
    }


def update_dividend_plan(
    *,
    annual_contribution_target: float | None = None,
    currency: str | None = None,
    plan_name: str | None = None,
    base_year: int | None = None,
    retirement_years: int | None = None,
    as_of: date | None = None,
) -> dict[str, Any]:
    """更新 Cash Anchor 年度投入计划，并返回更新后的快照。"""

    _ensure_cash_anchor_data_files()
    current = read_dividend_plan()
    updated = DividendPlan(
        plan_name=plan_name or current.plan_name,
        base_year=base_year if base_year is not None else current.base_year,
        retirement_years=retirement_years if retirement_years is not None else current.retirement_years,
        annual_contribution_target=(
            annual_contribution_target
            if annual_contribution_target is not None
            else current.annual_contribution_target
        ),
        currency=currency or current.currency,
        single_position_limit_pct=current.single_position_limit_pct,
        core_position_limit_pct=current.core_position_limit_pct,
        cyclical_position_limit_pct=current.cyclical_position_limit_pct,
        cyclical_total_limit_pct=current.cyclical_total_limit_pct,
        industry_limit_default_pct=current.industry_limit_default_pct,
        industry_limit_pct=dict(current.industry_limit_pct),
        cyclical_industries=list(current.cyclical_industries),
        symbol_limit_types=dict(current.symbol_limit_types),
        symbol_industries=dict(current.symbol_industries),
    )
    if updated.annual_contribution_target < 0:
        raise ValueError("年度投入目标不能为负数。")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _write_dividend_plan(updated)
    snapshot = build_portfolio_snapshot(as_of=as_of)
    snapshot["dividend_plan_path"] = str(DIVIDEND_PLAN_PATH)
    return snapshot


def upsert_holding(
    *,
    symbol: str,
    name: str = "",
    market: str = "A股",
    currency: str = "CNY",
    shares: float,
    cost_price: float,
    current_price: float,
    annual_dividend_per_share: float,
    tax_rate: float = 0.0,
    notes: str = "",
    as_of: date | None = None,
) -> dict[str, Any]:
    """新增或更新一条 Cash Anchor 持仓，并返回更新后的组合快照。"""

    clean_symbol = symbol.strip()
    if not clean_symbol:
        raise ValueError("持仓代码不能为空。")
    if shares < 0:
        raise ValueError("持仓份额不能为负数。")
    if cost_price < 0 or current_price < 0 or annual_dividend_per_share < 0:
        raise ValueError("价格和每股分红不能为负数。")
    if tax_rate < 0 or tax_rate > 1:
        raise ValueError("税率必须在 0 到 1 之间。")

    _ensure_cash_anchor_data_files()
    holdings = read_holdings()
    updated = Holding(
        symbol=clean_symbol,
        name=name or clean_symbol,
        market=market,
        currency=currency,
        shares=shares,
        cost_price=cost_price,
        current_price=current_price,
        annual_dividend_per_share=annual_dividend_per_share,
        tax_rate=tax_rate,
        notes=notes,
    )

    rows: list[Holding] = []
    replaced = False
    for item in holdings:
        if item.symbol == clean_symbol:
            rows.append(updated)
            replaced = True
        else:
            rows.append(item)
    if not replaced:
        rows.append(updated)

    _write_holdings(rows)
    snapshot = build_portfolio_snapshot(as_of=as_of)
    snapshot["holdings_path"] = str(HOLDINGS_PATH)
    snapshot["updated_holding"] = asdict(updated)
    snapshot["holding_action"] = "updated" if replaced else "created"
    return snapshot


def record_sync_event(
    *,
    symbol: str,
    shares: float,
    price: float,
    amount: float,
    currency: str,
    source: str,
    notes: str = "",
    event_date: date | None = None,
) -> None:
    """记录外部只读同步事件，保留账本审计轨迹。"""

    if shares < 0:
        raise ValueError("同步份额不能为负数。")
    target_date = event_date or date.today()
    _ensure_cash_anchor_data_files()
    _append_portfolio_event(
        PortfolioEvent(
            date=target_date.isoformat(),
            event_type="sync_snapshot",
            symbol=_required_symbol(symbol),
            shares=shares,
            price=price,
            amount=amount,
            currency=currency,
            source=source,
            notes=notes,
        )
    )


def record_buy(
    *,
    symbol: str,
    shares: float,
    price: float,
    trade_date: date | None = None,
    name: str = "",
    market: str = "A股",
    currency: str = "CNY",
    current_price: float | None = None,
    annual_dividend_per_share: float | None = None,
    tax_rate: float | None = None,
    notes: str = "",
) -> dict[str, Any]:
    """记录买入事件，并用加权成本更新持仓。"""

    if shares <= 0:
        raise ValueError("买入份额必须大于 0。")
    if price < 0:
        raise ValueError("买入价格不能为负数。")
    target_date = trade_date or date.today()
    clean_symbol = _required_symbol(symbol)
    _ensure_cash_anchor_data_files()
    holdings = read_holdings()
    current = _find_holding(holdings, clean_symbol)
    old_shares = current.shares if current else 0.0
    old_cost_basis = old_shares * (current.cost_price if current else 0.0)
    new_shares = old_shares + shares
    new_cost = (old_cost_basis + shares * price) / new_shares
    updated = Holding(
        symbol=clean_symbol,
        name=name or (current.name if current else clean_symbol),
        market=market or (current.market if current else "A股"),
        currency=currency or (current.currency if current else "CNY"),
        shares=new_shares,
        cost_price=new_cost,
        current_price=current_price if current_price is not None else (current.current_price if current else price),
        annual_dividend_per_share=(
            annual_dividend_per_share
            if annual_dividend_per_share is not None
            else (current.annual_dividend_per_share if current else 0.0)
        ),
        tax_rate=tax_rate if tax_rate is not None else (current.tax_rate if current else 0.0),
        notes=notes or (current.notes if current else ""),
    )
    _replace_holding(holdings, updated)
    _append_portfolio_event(
        PortfolioEvent(
            date=target_date.isoformat(),
            event_type="buy",
            symbol=clean_symbol,
            shares=shares,
            price=price,
            amount=shares * price,
            currency=updated.currency,
            source="manual",
            notes=notes,
        )
    )
    snapshot = build_portfolio_snapshot(as_of=target_date)
    snapshot["updated_holding"] = asdict(updated)
    snapshot["event_path"] = str(PORTFOLIO_EVENTS_PATH)
    return snapshot


def record_sell(
    *,
    symbol: str,
    shares: float,
    price: float,
    trade_date: date | None = None,
    notes: str = "",
) -> dict[str, Any]:
    """记录卖出事件，并减少本地持仓份额。"""

    if shares <= 0:
        raise ValueError("卖出份额必须大于 0。")
    if price < 0:
        raise ValueError("卖出价格不能为负数。")
    target_date = trade_date or date.today()
    clean_symbol = _required_symbol(symbol)
    _ensure_cash_anchor_data_files()
    holdings = read_holdings()
    current = _find_holding(holdings, clean_symbol)
    if current is None:
        raise ValueError(f"未找到持仓：{clean_symbol}")
    if shares > current.shares:
        raise ValueError(f"卖出份额超过当前持仓：当前 {current.shares:g}，卖出 {shares:g}")
    remaining = current.shares - shares
    if remaining == 0:
        rows = [item for item in holdings if item.symbol != clean_symbol]
        _write_holdings(rows)
    else:
        updated = Holding(
            **{
                **asdict(current),
                "shares": remaining,
                "current_price": price,
                "notes": notes or current.notes,
            }
        )
        _replace_holding(holdings, updated)
    _append_portfolio_event(
        PortfolioEvent(
            date=target_date.isoformat(),
            event_type="sell",
            symbol=clean_symbol,
            shares=shares,
            price=price,
            amount=shares * price,
            currency=current.currency,
            source="manual",
            notes=notes,
        )
    )
    snapshot = build_portfolio_snapshot(as_of=target_date)
    snapshot["sold_symbol"] = clean_symbol
    snapshot["remaining_shares"] = remaining
    snapshot["event_path"] = str(PORTFOLIO_EVENTS_PATH)
    return snapshot


def record_dividend(
    *,
    symbol: str,
    amount: float,
    dividend_date: date | None = None,
    currency: str = "CNY",
    source: str = "manual",
    notes: str = "",
) -> dict[str, Any]:
    """记录一次现金分红到账。"""

    if amount < 0:
        raise ValueError("分红金额不能为负数。")
    target_date = dividend_date or date.today()
    clean_symbol = _required_symbol(symbol)
    _ensure_cash_anchor_data_files()
    _append_portfolio_event(
        PortfolioEvent(
            date=target_date.isoformat(),
            event_type="dividend",
            symbol=clean_symbol,
            shares=0.0,
            price=0.0,
            amount=amount,
            currency=currency,
            source=source,
            notes=notes,
        )
    )
    return {
        "date": target_date.isoformat(),
        "symbol": clean_symbol,
        "amount": amount,
        "currency": currency,
        "source": source,
        "event_path": str(PORTFOLIO_EVENTS_PATH),
    }


def format_contribution_progress(result: dict[str, Any]) -> str:
    """格式化一次投入记录后的年度进度。"""

    progress = float(result.get("annual_contribution_progress") or 0)
    return (
        "已记录工资投入：\n"
        f"- 日期：{result['date']}\n"
        f"- 本次投入：{_money(result['amount'], result['currency'])}\n"
        f"- 今年已投入：{_money(result['current_year_contribution'], result['currency'])}\n"
        f"- 年度目标：{_money(result['annual_contribution_target'], result['currency'])}\n"
        f"- 完成进度：{progress:.1%}\n"
        f"- 距离目标还差：{_money(result['annual_contribution_gap'], result['currency'])}\n"
        f"- 账本：{result['capital_flows_path']}"
    )


def format_plan_progress(snapshot: dict[str, Any]) -> str:
    """格式化年度投入计划更新后的进度。"""

    plan = snapshot["plan"]
    summary = snapshot["summary"]
    currency = plan["currency"]
    return (
        "已更新 Cash Anchor 年度投入计划：\n"
        f"- 年度工资投入目标：{_money(plan['annual_contribution_target'], currency)}\n"
        f"- 今年已投入：{_money(summary['current_year_contribution'], currency)}\n"
        f"- 投入完成进度：{float(summary['annual_contribution_progress'] or 0):.1%}\n"
        f"- 今年投入缺口：{_money(summary['annual_contribution_gap'], currency)}\n"
        f"- 当前净年分红能力：{_money(summary['net_annual_dividend'], currency)}\n"
        f"- 计划文件：{snapshot['dividend_plan_path']}"
    )


def format_holding_progress(snapshot: dict[str, Any]) -> str:
    """格式化持仓更新后的现金流能力。"""

    holding = snapshot["updated_holding"]
    summary = snapshot["summary"]
    action = "已更新" if snapshot["holding_action"] == "updated" else "已新增"
    currency = holding["currency"]
    gross = float(holding["shares"]) * float(holding["annual_dividend_per_share"])
    net = gross * max(1 - float(holding["tax_rate"]), 0)
    dividend_text = (
        _money(holding["annual_dividend_per_share"], currency)
        if float(holding["annual_dividend_per_share"]) > 0
        else "待估算"
    )
    current_text = (
        "待查询"
        if "current_price=pending_quote" in str(holding.get("notes") or "")
        else _money(holding["current_price"], currency)
    )
    return (
        f"{action}持仓：{holding['symbol']} {holding['name']}\n"
        f"- 份额：{holding['shares']:,.2f}\n"
        f"- 成本价：{_money(holding['cost_price'], currency)}\n"
        f"- 当前价：{current_text}\n"
        f"- 单位年分红：{dividend_text}\n"
        f"- 组合预估税后年分红：{_money(summary['net_annual_dividend'], currency)}\n"
        f"- 账本：{snapshot['holdings_path']}"
    )


def format_buy_progress(snapshot: dict[str, Any]) -> str:
    holding = snapshot["updated_holding"]
    summary = snapshot["summary"]
    currency = holding["currency"]
    return (
        f"已记录买入：{holding['symbol']} {holding['name']}\n"
        f"- 当前份额：{holding['shares']:,.2f}\n"
        f"- 更新后成本价：{_money(holding['cost_price'], currency)}\n"
        f"- 预估税后年分红：{_money(summary['net_annual_dividend'], currency)}\n"
        f"- 事件账本：{snapshot['event_path']}"
    )


def format_sell_progress(snapshot: dict[str, Any]) -> str:
    summary = snapshot["summary"]
    currency = snapshot["plan"]["currency"]
    return (
        f"已记录卖出：{snapshot['sold_symbol']}\n"
        f"- 剩余份额：{snapshot['remaining_shares']:,.2f}\n"
        f"- 组合预估税后年分红：{_money(summary['net_annual_dividend'], currency)}\n"
        f"- 事件账本：{snapshot['event_path']}"
    )


def format_dividend_event(result: dict[str, Any]) -> str:
    return (
        "已记录现金分红：\n"
        f"- 日期：{result['date']}\n"
        f"- 标的：{result['symbol']}\n"
        f"- 到账金额：{_money(result['amount'], result['currency'])}\n"
        f"- 事件账本：{result['event_path']}"
    )


def format_snapshot(snapshot: dict[str, Any]) -> str:
    summary = snapshot["summary"]
    plan = snapshot["plan"]
    currency = plan["currency"]
    yield_lines = _format_dividend_yield_estimate_lines(snapshot)
    limit_line = _format_position_limit_line(snapshot)
    return (
        "Cash Anchor 持仓快照：\n"
        f"- 持仓数量：{summary['holding_count']}\n"
        f"- 总成本：{_money(summary['total_cost'], currency)}\n"
        f"- 当前市值：{_money(summary['total_market_value'], currency)}\n"
        f"- 预估税后年分红：{_money(summary['net_annual_dividend'], currency)}\n"
        f"- 成本税后股息率：{float(summary['net_yield_on_cost'] or 0):.2%}\n"
        f"{yield_lines}"
        f"{limit_line}"
        f"- 当前年投入：{_money(summary['current_year_contribution'], currency)}\n"
        f"- 投入目标进度：{float(summary['annual_contribution_progress'] or 0):.1%}\n"
        f"- 持仓账本：{snapshot['data_files']['holdings']}\n"
        f"- 事件账本：{snapshot['data_files']['portfolio_events']}"
    )


def _format_dividend_yield_estimate_lines(snapshot: dict[str, Any]) -> str:
    estimate = (
        snapshot.get("dividend_analysis", {})
        .get("portfolio_dividend_yield_estimate", {})
    )
    groups = estimate.get("by_market") or []
    if not groups:
        return ""
    lines = []
    for group in groups:
        market = group.get("market") or "UNKNOWN"
        currency = group.get("currency") or ""
        lines.append(
            f"- {market}综合股息率：{float(group.get('current_yield') or 0):.2%}"
            f"（年化现金 {_money(group.get('estimated_annual_cash'), currency)}）"
        )
    total = estimate.get("portfolio_total") or {}
    if total.get("status") == "ok":
        lines.append(f"- 全组合综合股息率：{float(total.get('current_yield') or 0):.2%}")
    elif total.get("status") == "requires_fx":
        lines.append("- 全组合综合股息率：需先确认汇率，当前按币种分开展示。")
    return "\n".join(lines) + "\n"


def _format_position_limit_line(snapshot: dict[str, Any]) -> str:
    analysis = snapshot.get("position_limit_analysis") if isinstance(snapshot.get("position_limit_analysis"), dict) else {}
    if not analysis:
        return ""
    status = str(analysis.get("status") or "unknown")
    label = {
        "ok": "正常",
        "near_limit": "接近上限",
        "over_limit": "已超限",
        "missing": "不可用",
    }.get(status, status)
    return f"- 仓位纪律：{label}（{analysis.get('scope') or 'A股红利池'}）\n"


def _write_holdings(holdings: list[Holding]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with HOLDINGS_PATH.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "symbol",
                "name",
                "market",
                "currency",
                "shares",
                "cost_price",
                "current_price",
                "annual_dividend_per_share",
                "tax_rate",
                "notes",
            ],
        )
        writer.writeheader()
        for item in holdings:
            row = asdict(item)
            row["shares"] = _format_decimal(float(row["shares"]), 6)
            for key in ["cost_price", "current_price", "annual_dividend_per_share"]:
                row[key] = _format_decimal(float(row[key]), 4)
            row["tax_rate"] = _format_decimal(float(row["tax_rate"]), 6)
            writer.writerow(row)


def read_holdings() -> list[Holding]:
    """读取 `data/holdings.csv`；文件不存在时返回空列表。"""

    if not HOLDINGS_PATH.exists():
        return []
    rows = _read_csv(HOLDINGS_PATH)
    return [
        Holding(
            symbol=str(row.get("symbol") or "").strip(),
            name=str(row.get("name") or "").strip(),
            market=str(row.get("market") or "").strip(),
            currency=str(row.get("currency") or "CNY").strip(),
            shares=_to_float(row.get("shares")),
            cost_price=_to_float(row.get("cost_price")),
            current_price=_to_float(row.get("current_price")),
            annual_dividend_per_share=_to_float(row.get("annual_dividend_per_share")),
            tax_rate=_to_float(row.get("tax_rate")),
            notes=str(row.get("notes") or "").strip(),
        )
        for row in rows
        if str(row.get("symbol") or "").strip()
    ]


def read_capital_flows() -> list[CapitalFlow]:
    """读取 `data/capital_flows.csv`；文件不存在时返回空列表。"""

    if not CAPITAL_FLOWS_PATH.exists():
        return []
    rows = _read_csv(CAPITAL_FLOWS_PATH)
    return [
        CapitalFlow(
            date=str(row.get("date") or "").strip(),
            amount=_to_float(row.get("amount")),
            currency=str(row.get("currency") or "CNY").strip(),
            source=str(row.get("source") or "").strip(),
            notes=str(row.get("notes") or "").strip(),
        )
        for row in rows
        if str(row.get("date") or "").strip()
    ]


def read_portfolio_events() -> list[PortfolioEvent]:
    """读取 `data/portfolio_events.csv`；文件不存在时返回空列表。"""

    if not PORTFOLIO_EVENTS_PATH.exists():
        return []
    rows = _read_csv(PORTFOLIO_EVENTS_PATH)
    return [
        PortfolioEvent(
            date=str(row.get("date") or "").strip(),
            event_type=str(row.get("event_type") or "").strip(),
            symbol=str(row.get("symbol") or "").strip(),
            shares=_to_float(row.get("shares")),
            price=_to_float(row.get("price")),
            amount=_to_float(row.get("amount")),
            currency=str(row.get("currency") or "CNY").strip(),
            source=str(row.get("source") or "").strip(),
            notes=str(row.get("notes") or "").strip(),
        )
        for row in rows
        if str(row.get("date") or "").strip()
    ]


def read_us_distribution_history() -> list[USDistributionRecord]:
    """读取美元收益基金历史每份分配记录。"""

    if not US_DISTRIBUTION_HISTORY_PATH.exists():
        return []
    rows = _read_csv(US_DISTRIBUTION_HISTORY_PATH)
    return [
        USDistributionRecord(
            symbol=str(row.get("symbol") or "").strip().upper(),
            ex_date=_normalize_date_text(row.get("ex_date")),
            payment_date=_normalize_date_text(row.get("payment_date")),
            record_date=_normalize_date_text(row.get("record_date")),
            amount_per_share=_to_float(row.get("amount_per_share")),
            currency=str(row.get("currency") or "USD").strip().upper(),
            source=str(row.get("source") or "").strip(),
            notes=str(row.get("notes") or "").strip(),
        )
        for row in rows
        if str(row.get("symbol") or "").strip() and _to_float(row.get("amount_per_share")) > 0
    ]


def upsert_us_distribution_history(records: list[USDistributionRecord]) -> dict[str, Any]:
    """写入美元收益基金历史分配记录，同一标的同一日期同一金额只保留一条。"""

    if not records:
        return {"created_count": 0, "updated_count": 0, "total_count": len(read_us_distribution_history())}
    _ensure_cash_anchor_data_files()
    existing = {
        _distribution_record_key(item): item
        for item in read_us_distribution_history()
    }
    created = 0
    updated = 0
    for raw in records:
        item = USDistributionRecord(
            symbol=raw.symbol.strip().upper(),
            ex_date=_normalize_date_text(raw.ex_date),
            payment_date=_normalize_date_text(raw.payment_date),
            record_date=_normalize_date_text(raw.record_date),
            amount_per_share=float(raw.amount_per_share),
            currency=(raw.currency or "USD").strip().upper(),
            source=raw.source.strip(),
            notes=raw.notes.strip(),
        )
        key = _distribution_record_key(item)
        if key in existing:
            updated += 1
        else:
            created += 1
        existing[key] = item
    rows = sorted(
        existing.values(),
        key=lambda item: (item.symbol, _distribution_effective_date(item), item.amount_per_share),
    )
    _write_us_distribution_history(rows)
    return {"created_count": created, "updated_count": updated, "total_count": len(rows)}


def read_dividend_plan() -> DividendPlan:
    """读取 `data/dividend_plan.yaml`；旧版目标年分红字段会被忽略。"""

    if not DIVIDEND_PLAN_PATH.exists():
        return DividendPlan()
    data = _read_simple_key_value_yaml(DIVIDEND_PLAN_PATH)
    default = DividendPlan()
    return DividendPlan(
        plan_name=str(data.get("plan_name") or "Cash Anchor 10 Year Retirement Plan"),
        base_year=int(_to_float(data.get("base_year")) or 2026),
        retirement_years=int(_to_float(data.get("retirement_years")) or 10),
        annual_contribution_target=_to_float(data.get("annual_contribution_target")),
        currency=str(data.get("currency") or "CNY"),
        single_position_limit_pct=_plan_float(data, "limit_single_normal_pct", default.single_position_limit_pct),
        core_position_limit_pct=_plan_float(data, "limit_single_core_pct", default.core_position_limit_pct),
        cyclical_position_limit_pct=_plan_float(data, "limit_single_cyclical_pct", default.cyclical_position_limit_pct),
        cyclical_total_limit_pct=_plan_float(data, "limit_cyclical_total_pct", default.cyclical_total_limit_pct),
        industry_limit_default_pct=_plan_float(data, "limit_industry_default_pct", default.industry_limit_default_pct),
        industry_limit_pct=_read_industry_limits(data, default.industry_limit_pct),
        cyclical_industries=_read_csv_text_list(data.get("limit_cyclical_industries"), default.cyclical_industries),
        symbol_limit_types=_read_symbol_text_map(data.get("limit_symbol_types"), default.symbol_limit_types),
        symbol_industries=_read_symbol_text_map(data.get("limit_symbol_industries"), default.symbol_industries),
    )


def _write_dividend_plan(plan: DividendPlan) -> None:
    lines = [
        f"plan_name: {plan.plan_name}",
        f"base_year: {plan.base_year}",
        f"retirement_years: {plan.retirement_years}",
        f"annual_contribution_target: {_format_amount(plan.annual_contribution_target)}",
        f"currency: {plan.currency}",
        "",
        "# Position limit rules use A-share dividend-pool market value as denominator.",
        f"limit_single_core_pct: {_format_decimal(plan.core_position_limit_pct, 4)}",
        f"limit_single_normal_pct: {_format_decimal(plan.single_position_limit_pct, 4)}",
        f"limit_single_cyclical_pct: {_format_decimal(plan.cyclical_position_limit_pct, 4)}",
        f"limit_cyclical_total_pct: {_format_decimal(plan.cyclical_total_limit_pct, 4)}",
        f"limit_industry_default_pct: {_format_decimal(plan.industry_limit_default_pct, 4)}",
    ]
    for industry, limit in sorted(plan.industry_limit_pct.items()):
        lines.append(f"limit_industry_{industry}_pct: {_format_decimal(limit, 4)}")
    lines.extend(
        [
            f"limit_cyclical_industries: {_format_text_list(plan.cyclical_industries)}",
            f"limit_symbol_types: {_format_text_map(plan.symbol_limit_types)}",
            f"limit_symbol_industries: {_format_text_map(plan.symbol_industries)}",
            "",
        ]
    )
    DIVIDEND_PLAN_PATH.write_text("\n".join(lines), encoding="utf-8")


def _ensure_cash_anchor_data_files() -> None:
    """初始化 Cash Anchor 私有账本文件。"""

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not DIVIDEND_PLAN_PATH.exists():
        template = TEMPLATE_DIR / "dividend_plan.yaml"
        if template.exists():
            DIVIDEND_PLAN_PATH.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            DIVIDEND_PLAN_PATH.write_text(
                "\n".join(
                    [
                        "plan_name: Cash Anchor 10 Year Retirement Plan",
                        "base_year: 2026",
                        "retirement_years: 10",
                        "annual_contribution_target: 50000",
                        "currency: CNY",
                        "limit_single_core_pct: 0.15",
                        "limit_single_normal_pct: 0.10",
                        "limit_single_cyclical_pct: 0.08",
                        "limit_cyclical_total_pct: 0.25",
                        "limit_industry_default_pct: 0.30",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
    if not CAPITAL_FLOWS_PATH.exists():
        CAPITAL_FLOWS_PATH.write_text(
            "date,amount,currency,source,notes\n",
            encoding="utf-8",
        )
    if not HOLDINGS_PATH.exists():
        HOLDINGS_PATH.write_text(
            "symbol,name,market,currency,shares,cost_price,current_price,annual_dividend_per_share,tax_rate,notes\n",
            encoding="utf-8",
        )
    if not PORTFOLIO_EVENTS_PATH.exists():
        PORTFOLIO_EVENTS_PATH.write_text(
            "date,event_type,symbol,shares,price,amount,currency,source,notes\n",
            encoding="utf-8",
        )
    if not US_DISTRIBUTION_HISTORY_PATH.exists():
        US_DISTRIBUTION_HISTORY_PATH.write_text(
            "symbol,ex_date,payment_date,record_date,amount_per_share,currency,source,notes\n",
            encoding="utf-8",
        )


def _position_metrics(holding: Holding) -> dict[str, Any]:
    cost_basis = holding.shares * holding.cost_price
    market_value = holding.shares * holding.current_price
    gross_dividend = holding.shares * holding.annual_dividend_per_share
    net_dividend = gross_dividend * max(1 - holding.tax_rate, 0)
    return {
        **asdict(holding),
        "cost_basis": round(cost_basis, 2),
        "market_value": round(market_value, 2),
        "gross_annual_dividend": round(gross_dividend, 2),
        "net_annual_dividend": round(net_dividend, 2),
        "yield_on_cost": _safe_ratio(gross_dividend, cost_basis),
        "current_yield": _safe_ratio(gross_dividend, market_value),
        "net_yield_on_cost": _safe_ratio(net_dividend, cost_basis),
        "unrealized_pnl": round(market_value - cost_basis, 2),
    }


def _build_dividend_analysis(
    holdings: list[Holding],
    positions: list[dict[str, Any]],
    events: list[PortfolioEvent],
    current_date: date,
    plan_currency: str,
) -> dict[str, Any]:
    current_year_dividends = [
        item for item in events if item.event_type == "dividend" and _parse_year(item.date) == current_date.year
    ]
    all_dividend_events = [item for item in events if item.event_type == "dividend"]
    gross_by_currency: defaultdict[str, float] = defaultdict(float)
    net_by_currency: defaultdict[str, float] = defaultdict(float)
    for position in positions:
        currency = str(position.get("currency") or plan_currency)
        gross_by_currency[currency] += float(position.get("gross_annual_dividend") or 0)
        net_by_currency[currency] += float(position.get("net_annual_dividend") or 0)

    received_by_currency: defaultdict[str, float] = defaultdict(float)
    received_by_symbol: dict[tuple[str, str], dict[str, Any]] = {}
    for event in current_year_dividends:
        received_by_currency[event.currency] += event.amount
        key = (event.symbol, event.currency)
        row = received_by_symbol.setdefault(
            key,
            {
                "symbol": event.symbol,
                "currency": event.currency,
                "amount": 0.0,
                "event_count": 0,
                "latest_date": event.date,
            },
        )
        row["amount"] += event.amount
        row["event_count"] += 1
        if event.date > str(row["latest_date"]):
            row["latest_date"] = event.date

    missing_annual_dividend = [
        _holding_identity(item)
        for item in holdings
        if item.shares > 0 and item.annual_dividend_per_share <= 0
    ]
    has_forecast = any(amount > 0 for amount in gross_by_currency.values())
    has_received = bool(current_year_dividends)
    if not holdings:
        status = "missing"
    elif not missing_annual_dividend and has_forecast:
        status = "ok"
    elif has_forecast or has_received:
        status = "partial"
    else:
        status = "missing"

    answer_constraints: list[str] = []
    if missing_annual_dividend:
        answer_constraints.append("持仓账本中部分或全部持仓缺少财报口径的每股年分红，只能统计已到账分红，不能完整估算全年预期分红。")
    if not current_year_dividends:
        answer_constraints.append("分红到账流水中今年没有分红事件，本地账本未记录今年分红到账。")

    us_income_distribution_forecast = _build_us_income_distribution_forecast(
        holdings,
        current_date=current_date,
    )
    portfolio_dividend_yield_estimate = _build_portfolio_dividend_yield_estimate(
        positions,
        us_income_distribution_forecast,
    )
    if us_income_distribution_forecast["positions"]:
        answer_constraints.append("QQQI/XQQI/TQQQ 等美元收益基金不能使用固定每股年分红，只能区分已到账分配和基于历史分配的滚动预测。")

    return {
        "status": status,
        "basis": {
            "forecast_source": "持仓账本里的每股年分红；写入前必须经过企业财报、利润分配公告或基金分配文件核验。",
            "received_source": "分红到账流水里的分红事件。",
            "accepted_source_order": [
                "实际到账的分红流水",
                "从企业财报或利润分配公告核验后写入持仓账本的每股年分红",
                "已披露的企业财报、利润分配公告、权益分派实施公告或基金分配文件",
            ],
            "rejected_sources": [
                "行情源返回的股息字段",
                "凭记忆估算的股息率或大概值",
                "把备兑基金上一期分配机械外推成固定年分红",
            ],
            "plan_file_role": "年度投入计划只存本金投入目标，不是逐标的分红表。",
        },
        "forecast_from_holdings": {
            "gross_annual_dividend_by_currency": _amount_rows(gross_by_currency),
            "net_annual_dividend_by_currency": _amount_rows(net_by_currency),
            "missing_annual_dividend_positions": missing_annual_dividend,
            "filled_position_count": len(holdings) - len(missing_annual_dividend),
            "missing_position_count": len(missing_annual_dividend),
        },
        "current_year_received": {
            "year": current_date.year,
            "event_count": len(current_year_dividends),
            "total_by_currency": _amount_rows(received_by_currency),
            "plan_currency": plan_currency,
            "plan_currency_amount": round(received_by_currency.get(plan_currency, 0.0), 2),
            "by_symbol": _rounded_rows(received_by_symbol.values(), amount_keys={"amount"}),
            "events": [asdict(item) for item in current_year_dividends],
        },
        "us_income_distribution_forecast": us_income_distribution_forecast,
        "portfolio_dividend_yield_estimate": portfolio_dividend_yield_estimate,
        "all_time_dividend_event_count": len(all_dividend_events),
        "answer_constraints": answer_constraints,
        "repair_actions": [
            "用 /dividend symbol=<code> amount=<amount> date=YYYY-MM-DD 记录已经到账的现金分红。",
            "核对公告、年报或基金分配文件后，用 /holding symbol=<code> ... dividend=<per_share> 更新标的每股年分红预估。",
            "用 /sync longbridge dividends 同步美元收益基金的到账分配和历史分配记录。",
        ],
    }


def _build_portfolio_dividend_yield_estimate(
    positions: list[dict[str, Any]],
    us_income_distribution_forecast: dict[str, Any],
    *,
    base_currency: str = "CNY",
    fx_rates: list[dict[str, Any]] | None = None,
    fx_source: str = "",
) -> dict[str, Any]:
    us_forecast_by_symbol = {
        _canonical_us_symbol(str(item.get("symbol") or "")): item
        for item in us_income_distribution_forecast.get("positions", [])
    }
    rows: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for position in positions:
        symbol = str(position.get("symbol") or "")
        market = _market_group(str(position.get("market") or ""), symbol)
        currency = str(position.get("currency") or "")
        market_value = float(position.get("market_value") or 0)
        cost_basis = float(position.get("cost_basis") or 0)
        if _is_us_income_symbol(symbol):
            selected_window, selected = _select_us_income_forecast_window(
                us_forecast_by_symbol.get(_canonical_us_symbol(symbol))
            )
            estimated_cash = float(selected.get("estimated_annual_cash") or 0) if selected else 0.0
            basis = _us_income_window_label(selected_window)
        else:
            selected_window = ""
            estimated_cash = float(position.get("net_annual_dividend") or 0)
            basis = "持仓账本中的财报/公告口径每股年分红"

        row = {
            "symbol": symbol,
            "name": position.get("name") or "",
            "market": market,
            "currency": currency,
            "market_value": round(market_value, 2),
            "cost_basis": round(cost_basis, 2),
            "estimated_annual_cash": round(estimated_cash, 2),
            "current_yield": _safe_ratio(estimated_cash, market_value),
            "yield_on_cost": _safe_ratio(estimated_cash, cost_basis),
            "basis": basis,
        }
        if selected_window:
            row["selected_window"] = selected_window
        if estimated_cash > 0 and market_value > 0:
            rows.append(row)
        else:
            missing.append(row)

    return {
        "policy": "A股按持仓账本每股年分红估算；美股备兑收益基金按历史分配滚动估算；跨币种总收益率需要明确汇率后才能合并。",
        "by_market": _yield_groups(rows, group_keys=("market", "currency")),
        "by_currency": _yield_groups(rows, group_keys=("currency",)),
        "portfolio_total": _portfolio_yield_total(
            rows,
            base_currency=base_currency,
            fx_rates=fx_rates or [],
            fx_source=fx_source,
        ),
        "positions": rows,
        "missing_positions": missing,
    }


def _select_us_income_forecast_window(item: dict[str, Any] | None) -> tuple[str, dict[str, Any] | None]:
    if not item:
        return "", None
    windows = [
        ("trailing_12m", item.get("trailing_12m") or {}, 10),
        ("trailing_6m", item.get("trailing_6m") or {}, 3),
        ("trailing_3m", item.get("trailing_3m") or {}, 1),
    ]
    for name, metrics, min_count in windows:
        if int(metrics.get("record_count") or 0) >= min_count and float(metrics.get("estimated_annual_cash") or 0) > 0:
            return name, metrics
    return "", None


def _us_income_window_label(window: str) -> str:
    labels = {
        "trailing_12m": "美元收益基金近12个月历史分配",
        "trailing_6m": "美元收益基金近6个月滚动年化分配",
        "trailing_3m": "美元收益基金近3个月滚动年化分配",
    }
    return labels.get(window, "美元收益基金历史分配不足，暂不估算")


def _yield_groups(rows: list[dict[str, Any]], *, group_keys: tuple[str, ...]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in rows:
        key = tuple(str(row.get(item) or "") for item in group_keys)
        group = groups.setdefault(
            key,
            {
                **{group_key: key[index] for index, group_key in enumerate(group_keys)},
                "position_count": 0,
                "symbols": [],
                "market_value": 0.0,
                "cost_basis": 0.0,
                "estimated_annual_cash": 0.0,
            },
        )
        group["position_count"] += 1
        group["symbols"].append(str(row.get("symbol") or ""))
        group["market_value"] += float(row.get("market_value") or 0)
        group["cost_basis"] += float(row.get("cost_basis") or 0)
        group["estimated_annual_cash"] += float(row.get("estimated_annual_cash") or 0)

    result = []
    for group in groups.values():
        estimated_cash = float(group["estimated_annual_cash"] or 0)
        market_value = float(group["market_value"] or 0)
        cost_basis = float(group["cost_basis"] or 0)
        result.append(
            {
                **group,
                "market_value": round(market_value, 2),
                "cost_basis": round(cost_basis, 2),
                "estimated_annual_cash": round(estimated_cash, 2),
                "current_yield": _safe_ratio(estimated_cash, market_value),
                "yield_on_cost": _safe_ratio(estimated_cash, cost_basis),
            }
        )
    return sorted(result, key=lambda item: tuple(str(item.get(key) or "") for key in group_keys))


def _portfolio_yield_total(
    rows: list[dict[str, Any]],
    *,
    base_currency: str,
    fx_rates: list[dict[str, Any]],
    fx_source: str,
) -> dict[str, Any]:
    currencies = sorted({str(item.get("currency") or "") for item in rows if item.get("currency")})
    by_currency = _yield_groups(rows, group_keys=("currency",))
    if len(currencies) == 1:
        row = by_currency[0] if by_currency else {}
        return {
            "status": "ok",
            "currency": currencies[0],
            "market_value": row.get("market_value", 0.0),
            "cost_basis": row.get("cost_basis", 0.0),
            "estimated_annual_cash": row.get("estimated_annual_cash", 0.0),
            "current_yield": row.get("current_yield", 0.0),
            "yield_on_cost": row.get("yield_on_cost", 0.0),
        }
    converted_market_value = 0.0
    converted_cost_basis = 0.0
    converted_cash = 0.0
    missing_rates: list[str] = []
    for row in by_currency:
        currency = str(row.get("currency") or "")
        market_value = _convert_currency_amount(float(row.get("market_value") or 0), currency, base_currency, fx_rates)
        cost_basis = _convert_currency_amount(float(row.get("cost_basis") or 0), currency, base_currency, fx_rates)
        annual_cash = _convert_currency_amount(float(row.get("estimated_annual_cash") or 0), currency, base_currency, fx_rates)
        if market_value is None or cost_basis is None or annual_cash is None:
            missing_rates.append(currency)
            continue
        converted_market_value += market_value
        converted_cost_basis += cost_basis
        converted_cash += annual_cash
    if not missing_rates and converted_market_value > 0:
        return {
            "status": "ok",
            "currency": base_currency,
            "fx_source": fx_source or "exchange_rates",
            "market_value": round(converted_market_value, 2),
            "cost_basis": round(converted_cost_basis, 2),
            "estimated_annual_cash": round(converted_cash, 2),
            "current_yield": _safe_ratio(converted_cash, converted_market_value),
            "yield_on_cost": _safe_ratio(converted_cash, converted_cost_basis),
            "by_currency": by_currency,
        }
    return {
        "status": "requires_fx",
        "reason": "组合同时包含多个币种；没有明确汇率来源时，不合并成单一综合股息率。",
        "missing_rate_currencies": sorted(set(missing_rates or currencies)),
        "by_currency": by_currency,
    }


def _convert_currency_amount(
    amount: float,
    from_currency: str,
    to_currency: str,
    fx_rates: list[dict[str, Any]],
) -> float | None:
    source = from_currency.strip().upper()
    target = to_currency.strip().upper()
    if source == target:
        return amount
    for row in fx_rates:
        base = str(row.get("base_currency") or "").strip().upper()
        other = str(row.get("other_currency") or "").strip().upper()
        rate = _to_float(row.get("average_rate"))
        if rate <= 0:
            continue
        if base == target and other == source:
            return amount * rate
        if base == source and other == target:
            return amount / rate
    return None


def _build_us_income_distribution_forecast(
    holdings: list[Holding],
    *,
    current_date: date,
) -> dict[str, Any]:
    history = read_us_distribution_history()
    rows: list[dict[str, Any]] = []
    totals: dict[str, defaultdict[str, float]] = {
        "trailing_3m": defaultdict(float),
        "trailing_6m": defaultdict(float),
        "trailing_12m": defaultdict(float),
    }
    for holding in holdings:
        if holding.shares <= 0 or not _is_us_income_symbol(holding.symbol):
            continue
        records = [
            item
            for item in history
            if _canonical_us_symbol(item.symbol) == _canonical_us_symbol(holding.symbol)
            and _distribution_effective_date_value(item) is not None
            and _distribution_effective_date_value(item) <= current_date
        ]
        records.sort(key=lambda item: _distribution_effective_date(item))
        windows = {
            "trailing_3m": _distribution_window_metrics(holding, records, current_date=current_date, days=92),
            "trailing_6m": _distribution_window_metrics(holding, records, current_date=current_date, days=183),
            "trailing_12m": _distribution_window_metrics(holding, records, current_date=current_date, days=366),
        }
        for window_name, metrics in windows.items():
            totals[window_name][holding.currency] += float(metrics.get("estimated_annual_cash") or 0)
        latest = records[-1] if records else None
        row = {
            "symbol": holding.symbol,
            "name": holding.name,
            "currency": holding.currency,
            "shares": holding.shares,
            "history_record_count": len(records),
            "latest_distribution": (
                {
                    "amount_per_share": round(latest.amount_per_share, 4),
                    "ex_date": latest.ex_date,
                    "payment_date": latest.payment_date,
                    "record_date": latest.record_date,
                    "source": latest.source,
                }
                if latest
                else None
            ),
            "trailing_3m": windows["trailing_3m"],
            "trailing_6m": windows["trailing_6m"],
            "trailing_12m": windows["trailing_12m"],
            "status": "ok" if windows["trailing_12m"]["record_count"] >= 6 else "insufficient_history" if records else "missing_history",
        }
        rows.append(row)

    return {
        "policy": (
            "美元备兑收益基金的分配不是固定股息。已到账金额只看分红流水；未来现金流只能用历史每份分配做滚动预测。"
        ),
        "history_file": str(US_DISTRIBUTION_HISTORY_PATH),
        "positions": rows,
        "estimated_annual_cash_by_currency": {
            key: _amount_rows(value)
            for key, value in totals.items()
        },
    }


def _distribution_window_metrics(
    holding: Holding,
    records: list[USDistributionRecord],
    *,
    current_date: date,
    days: int,
) -> dict[str, Any]:
    start = current_date - timedelta(days=days)
    selected = [
        item
        for item in records
        if (effective_date := _distribution_effective_date_value(item)) is not None
        and start < effective_date <= current_date
    ]
    amount_per_share = sum(item.amount_per_share for item in selected)
    annualized_per_share = amount_per_share * 365 / days if days > 0 else 0.0
    estimated_cash = annualized_per_share * holding.shares
    return {
        "window_days": days,
        "record_count": len(selected),
        "amount_per_share": round(amount_per_share, 4),
        "annualized_per_share": round(annualized_per_share, 4),
        "estimated_annual_cash": round(estimated_cash, 2),
        "yield_on_cost": _safe_ratio(annualized_per_share, holding.cost_price),
        "current_yield": _safe_ratio(annualized_per_share, holding.current_price),
    }


def _build_market_breakdown(positions: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for position in positions:
        market = _market_group(str(position.get("market") or ""), str(position.get("symbol") or ""))
        currency = str(position.get("currency") or "")
        key = (market, currency)
        row = groups.setdefault(
            key,
            {
                "market": market,
                "currency": currency,
                "holding_count": 0,
                "symbols": [],
                "total_cost": 0.0,
                "total_market_value": 0.0,
                "gross_annual_dividend": 0.0,
                "net_annual_dividend": 0.0,
            },
        )
        row["holding_count"] += 1
        row["symbols"].append(str(position.get("symbol") or ""))
        row["total_cost"] += float(position.get("cost_basis") or 0)
        row["total_market_value"] += float(position.get("market_value") or 0)
        row["gross_annual_dividend"] += float(position.get("gross_annual_dividend") or 0)
        row["net_annual_dividend"] += float(position.get("net_annual_dividend") or 0)
    rows = _rounded_rows(groups.values(), amount_keys={"total_cost", "total_market_value", "gross_annual_dividend", "net_annual_dividend"})
    return {
        "groups": sorted(rows, key=lambda item: (str(item["market"]), str(item["currency"]))),
        "markets_present": sorted({str(item["market"]) for item in rows}),
        "scope_policy": "境内红利问题只回答 A 股和港股分组；美元收益持仓除非用户要求现金锚点总览，否则单独归入美元收益框架。",
    }


def _build_position_limit_analysis(positions: list[dict[str, Any]], plan: DividendPlan) -> dict[str, Any]:
    cn_positions = [
        dict(item)
        for item in positions
        if _market_group(str(item.get("market") or ""), str(item.get("symbol") or "")) == "A股"
        and _to_float(item.get("market_value")) > 0
    ]
    denominator = sum(_to_float(item.get("market_value")) for item in cn_positions)
    if denominator <= 0:
        return {
            "status": "missing",
            "scope": "A股红利池",
            "denominator_market_value": 0.0,
            "policy": "没有可用 A 股市值，无法计算单票和行业仓位上限。",
            "positions": [],
            "industries": [],
            "cyclical_total": {},
            "warnings": ["A 股红利池市值为 0，仓位上限分析不可用。"],
        }

    position_rows: list[dict[str, Any]] = []
    position_contexts: list[dict[str, Any]] = []
    industry_totals: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    for position in cn_positions:
        symbol = str(position.get("symbol") or "")
        canonical = _canonical_symbol(symbol)
        market_value = _to_float(position.get("market_value"))
        weight = _safe_ratio(market_value, denominator)
        industry = _symbol_industry(canonical, position, plan)
        limit_type = _symbol_limit_type(canonical, plan, industry)
        limit_pct = _single_position_limit(limit_type, plan)
        position_contexts.append(
            {
                "position": position,
                "symbol": symbol,
                "market_value": market_value,
                "weight": weight,
                "industry": industry,
                "limit_type": limit_type,
                "limit_pct": limit_pct,
            }
        )
        industry_row = industry_totals.setdefault(
            industry,
            {
                "industry": industry,
                "industry_label": INDUSTRY_LABELS.get(industry, industry),
                "symbols": [],
                "market_value": 0.0,
            },
        )
        industry_row["symbols"].append(symbol)
        industry_row["market_value"] += market_value
        if industry == "unknown":
            warnings.append(f"{symbol} 缺少行业分类，已按默认行业上限处理。")

    industry_rows: list[dict[str, Any]] = []
    for industry, raw in industry_totals.items():
        market_value = _to_float(raw.get("market_value"))
        weight = _safe_ratio(market_value, denominator)
        limit_pct = plan.industry_limit_pct.get(industry, plan.industry_limit_default_pct)
        industry_rows.append(
            {
                "industry": industry,
                "industry_label": raw.get("industry_label") or industry,
                "symbols": raw.get("symbols") or [],
                "market_value": round(market_value, 2),
                "weight": weight,
                "limit_pct": limit_pct,
                "status": _limit_status(weight, limit_pct),
                "can_add": weight < limit_pct,
                "remaining_market_value_to_limit": round(max(limit_pct - weight, 0) * denominator, 2),
            }
        )

    cyclical_industries = set(plan.cyclical_industries)
    cyclical_value = sum(
        _to_float(item.get("market_value"))
        for item in industry_rows
        if str(item.get("industry") or "") in cyclical_industries
    )
    cyclical_weight = _safe_ratio(cyclical_value, denominator)
    cyclical_total = {
        "industries": sorted(cyclical_industries),
        "market_value": round(cyclical_value, 2),
        "weight": cyclical_weight,
        "limit_pct": plan.cyclical_total_limit_pct,
        "status": _limit_status(cyclical_weight, plan.cyclical_total_limit_pct),
        "can_add": cyclical_weight < plan.cyclical_total_limit_pct,
        "remaining_market_value_to_limit": round(
            max(plan.cyclical_total_limit_pct - cyclical_weight, 0) * denominator,
            2,
        ),
    }

    industry_values = {
        industry: _to_float(raw.get("market_value"))
        for industry, raw in industry_totals.items()
    }
    for context in position_contexts:
        position = context["position"]
        industry = str(context["industry"])
        market_value = _to_float(context["market_value"])
        weight = _to_float(context["weight"])
        limit_pct = _to_float(context["limit_pct"])
        guardrail = _build_add_guardrail(
            market_value=market_value,
            denominator=denominator,
            single_limit_pct=limit_pct,
            industry=industry,
            industry_market_value=industry_values.get(industry, 0.0),
            industry_limit_pct=plan.industry_limit_pct.get(industry, plan.industry_limit_default_pct),
            cyclical_market_value=cyclical_value,
            cyclical_limit_pct=plan.cyclical_total_limit_pct,
            is_cyclical=industry in cyclical_industries,
            current_price=_to_float(position.get("current_price")),
        )
        position_rows.append(
            {
                "symbol": context["symbol"],
                "name": position.get("name") or "",
                "market_value": round(market_value, 2),
                "weight": weight,
                "limit_type": context["limit_type"],
                "limit_type_label": LIMIT_TYPE_LABELS.get(str(context["limit_type"]), str(context["limit_type"])),
                "limit_pct": limit_pct,
                "status": _limit_status(weight, limit_pct),
                "can_add": guardrail["can_add"],
                "remaining_market_value_to_limit": round(max(limit_pct - weight, 0) * denominator, 2),
                "strict_max_add_market_value": guardrail["strict_max_add_market_value"],
                "max_add_shares_estimate": guardrail["max_add_shares_estimate"],
                "max_add_round_lot_shares": guardrail["max_add_round_lot_shares"],
                "add_guardrail": guardrail,
                "industry": industry,
                "industry_label": INDUSTRY_LABELS.get(industry, industry),
            }
        )

    position_rows.sort(key=lambda item: float(item["weight"]), reverse=True)
    industry_rows.sort(key=lambda item: float(item["weight"]), reverse=True)
    statuses = [str(item.get("status")) for item in position_rows + industry_rows + [cyclical_total]]
    return {
        "status": "over_limit" if "over_limit" in statuses else "near_limit" if "near_limit" in statuses else "ok",
        "scope": "A股红利池",
        "denominator_market_value": round(denominator, 2),
        "policy": "单票、行业和强周期上限均按 A 股红利池市值口径计算；美元收益持仓不参与该约束。",
        "trade_guardrail_policy": "严格可加额度按买入后 A 股红利池分母重新计算：min((上限比例 * 当前池市值 - 当前约束市值) / (1 - 上限比例))。低于或等于 0 时不得新增买入。",
        "limit_source": str(DIVIDEND_PLAN_PATH),
        "positions": position_rows,
        "industries": industry_rows,
        "cyclical_total": cyclical_total,
        "warnings": _dedupe_text(warnings),
    }


def _data_quality_with_position_limits(
    quality: dict[str, Any],
    position_limit_analysis: dict[str, Any],
) -> dict[str, Any]:
    result = dict(quality)
    warnings = list(result.get("warnings") or [])
    status = str(position_limit_analysis.get("status") or "")
    if status == "over_limit":
        warnings.append("仓位纪律发现超限：单票、行业或强周期仓位已经超过结构化上限。")
    elif status == "near_limit":
        warnings.append("仓位纪律接近上限：新增买入前必须先核对 position_limit_analysis。")
    warnings.extend(str(item) for item in position_limit_analysis.get("warnings") or [])
    result["position_limit_status"] = status or "unknown"
    result["warnings"] = _dedupe_text(warnings)
    result["status"] = "has_gaps" if result["warnings"] else "ok"
    return result


def _build_currency_breakdown(
    positions: list[dict[str, Any]],
    flows: list[CapitalFlow],
    events: list[PortfolioEvent],
    current_date: date,
) -> dict[str, Any]:
    position_totals: dict[str, dict[str, Any]] = {}
    for position in positions:
        currency = str(position.get("currency") or "")
        row = position_totals.setdefault(
            currency,
            {
                "currency": currency,
                "holding_count": 0,
                "total_cost": 0.0,
                "total_market_value": 0.0,
                "gross_annual_dividend": 0.0,
                "net_annual_dividend": 0.0,
            },
        )
        row["holding_count"] += 1
        row["total_cost"] += float(position.get("cost_basis") or 0)
        row["total_market_value"] += float(position.get("market_value") or 0)
        row["gross_annual_dividend"] += float(position.get("gross_annual_dividend") or 0)
        row["net_annual_dividend"] += float(position.get("net_annual_dividend") or 0)

    contributions: defaultdict[str, float] = defaultdict(float)
    dividends: defaultdict[str, float] = defaultdict(float)
    for flow in flows:
        if _parse_year(flow.date) == current_date.year:
            contributions[flow.currency] += flow.amount
    for event in events:
        if event.event_type == "dividend" and _parse_year(event.date) == current_date.year:
            dividends[event.currency] += event.amount

    currencies = sorted(currency for currency in position_totals if currency)
    return {
        "position_currencies": currencies,
        "is_mixed_currency": len(currencies) > 1,
        "position_totals_by_currency": sorted(
            _rounded_rows(position_totals.values(), amount_keys={"total_cost", "total_market_value", "gross_annual_dividend", "net_annual_dividend"}),
            key=lambda item: str(item["currency"]),
        ),
        "current_year_contribution_by_currency": _amount_rows(contributions),
        "current_year_dividend_received_by_currency": _amount_rows(dividends),
        "aggregation_policy": "没有明确汇率来源时，不把跨币种成本、市值或分红直接合并成人民币。",
    }


def _fetch_exchange_rates_for_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    currencies = list(
        (snapshot.get("currency_breakdown") or {}).get("position_currencies") or []
    )
    if len(currencies) <= 1:
        return {
            "status": "not_needed",
            "source": "none",
            "rates": [],
        }
    try:
        from src.longbridge_provider import fetch_longbridge_exchange_rates

        rates = fetch_longbridge_exchange_rates()
    except Exception as exc:
        return {
            "status": "error",
            "source": "longbridge_exchange_rate",
            "rates": [],
            "error": str(exc),
        }
    return {
        "status": "ok",
        "source": "longbridge_exchange_rate",
        "rates": [asdict(item) for item in rates],
    }


def _build_data_quality(
    holdings: list[Holding],
    events: list[PortfolioEvent],
    current_date: date,
) -> dict[str, Any]:
    pending_quote_symbols = [
        _holding_identity(item)
        for item in holdings
        if "current_price=pending_quote" in item.notes
    ]
    missing_annual_dividend_symbols = [
        _holding_identity(item)
        for item in holdings
        if item.shares > 0 and item.annual_dividend_per_share <= 0
    ]
    duplicate_groups = _duplicate_symbol_groups(holdings)
    currencies = sorted({item.currency for item in holdings if item.currency})
    current_year_dividend_count = sum(
        1 for item in events if item.event_type == "dividend" and _parse_year(item.date) == current_date.year
    )
    warnings: list[str] = []
    if pending_quote_symbols:
        warnings.append("当前价待查询只影响最新价、动态股息率和 MA120，不影响已到账分红流水统计。")
    if missing_annual_dividend_symbols:
        warnings.append("每股年分红缺失会影响全年预估分红和股息率计算，但不能覆盖 portfolio_events 中的实际到账事实。")
    if len(currencies) > 1:
        warnings.append("持仓包含多个币种，不能把成本、市值或分红直接汇总为单一 RMB 金额。")
    if duplicate_groups:
        warnings.append("发现同一代码的带后缀/不带后缀重复行，分析前应提示人工确认是否需要合并。")
    return {
        "status": "has_gaps" if warnings else "ok",
        "pending_quote_symbols": pending_quote_symbols,
        "missing_annual_dividend_symbols": missing_annual_dividend_symbols,
        "duplicate_symbol_groups": duplicate_groups,
        "position_currencies": currencies,
        "current_year_dividend_event_count": current_year_dividend_count,
        "warnings": warnings,
    }


def _build_market_data_summary(market_data: dict[str, Any]) -> dict[str, Any]:
    status_counts: defaultdict[str, int] = defaultdict(int)
    error_symbols: list[dict[str, str]] = []
    quote_missing_symbols: list[str] = []
    dividend_fields_ignored_symbols: list[str] = []
    for symbol, payload in market_data.items():
        if not isinstance(payload, dict):
            status_counts["unknown"] += 1
            continue
        status = str(payload.get("status") or "unknown")
        status_counts[status] += 1
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        if status == "error":
            error_symbols.append({"symbol": symbol, "error": str(payload.get("error") or "")})
        if data.get("price_status") == "missing":
            quote_missing_symbols.append(symbol)
        if data.get("cashflow_dividend_usable") is False:
            dividend_fields_ignored_symbols.append(symbol)
    return {
        "status_counts": dict(sorted(status_counts.items())),
        "error_symbols": error_symbols,
        "quote_missing_symbols": sorted(quote_missing_symbols),
        "dividend_fields_ignored_symbols": sorted(dividend_fields_ignored_symbols),
        "quote_dependent_metrics": ["latest_price", "MA120", "unrealized_pnl_from_latest_quote"],
        "ledger_dependent_metrics": ["今年已到账分红", "持仓账本里的每股年分红预估"],
    }


def _positions_with_market_data(
    positions: list[dict[str, Any]],
    market_data: dict[str, Any],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for position in positions:
        row = dict(position)
        symbol = str(row.get("symbol") or "")
        quote = market_data.get(symbol) or market_data.get(_canonical_symbol(symbol))
        data = quote.get("data") if isinstance(quote, dict) and isinstance(quote.get("data"), dict) else {}
        current_price = _to_float(data.get("current_price"))
        shares = _to_float(row.get("shares"))
        if current_price > 0 and shares > 0:
            market_value = shares * current_price
            estimated_cash = _to_float(row.get("net_annual_dividend") or row.get("gross_annual_dividend"))
            row["current_price"] = current_price
            row["market_value"] = round(market_value, 2)
            row["current_yield"] = _safe_ratio(estimated_cash, market_value)
            row["quote_source_for_yield"] = data.get("quote_source") or quote.get("source") or ""
        result.append(row)
    return result


def _market_data_for_portfolio_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep quote data, but prevent quote-provider dividends from becoming cash-flow facts."""

    clean = dict(payload)
    data = dict(clean.get("data") or {}) if isinstance(clean.get("data"), dict) else {}
    ignored_fields = []
    for key in ("annual_dividend_per_share", "dividend_status"):
        if key in data:
            ignored_fields.append(key)
            data.pop(key, None)
    data["cashflow_dividend_usable"] = False
    data["dividend_policy"] = "行情源股息字段不能用于现金锚点收入计算；必须使用企业披露文件、持仓账本或分红到账流水。"
    if ignored_fields:
        data["ignored_dividend_fields"] = ignored_fields
    clean["data"] = data
    return clean


def _holding_identity(holding: Holding) -> dict[str, Any]:
    return {
        "symbol": holding.symbol,
        "name": holding.name,
        "market": holding.market,
        "currency": holding.currency,
        "shares": holding.shares,
    }


def _symbol_limit_type(canonical_symbol: str, plan: DividendPlan, industry: str = "") -> str:
    value = str(plan.symbol_limit_types.get(canonical_symbol) or "").strip().lower()
    if value in LIMIT_TYPE_LABELS:
        return value
    if industry and industry in set(plan.cyclical_industries):
        return "cyclical"
    return "normal"


def _symbol_industry(canonical_symbol: str, position: dict[str, Any], plan: DividendPlan) -> str:
    configured = str(plan.symbol_industries.get(canonical_symbol) or "").strip().lower()
    if configured:
        return configured
    name = str(position.get("name") or "")
    if "银行" in name:
        return "bank"
    if "保险" in name or "平安" in name:
        return "insurance"
    if any(term in name for term in ("煤", "资源", "有色")):
        return "resource"
    if any(term in name for term in ("电力", "核电", "水电", "能源")):
        return "utility"
    if any(term in name for term in ("移动", "电信", "联通")):
        return "telecom"
    if any(term in name for term in ("啤酒", "美的", "伊利", "消费")):
        return "consumer"
    return "unknown"


def _single_position_limit(limit_type: str, plan: DividendPlan) -> float:
    if limit_type == "core":
        return plan.core_position_limit_pct
    if limit_type == "cyclical":
        return plan.cyclical_position_limit_pct
    return plan.single_position_limit_pct


def _limit_status(weight: float, limit_pct: float) -> str:
    if limit_pct <= 0:
        return "unknown"
    if weight > limit_pct + 1e-9:
        return "over_limit"
    if weight >= limit_pct * 0.9:
        return "near_limit"
    return "ok"


def _build_add_guardrail(
    *,
    market_value: float,
    denominator: float,
    single_limit_pct: float,
    industry: str,
    industry_market_value: float,
    industry_limit_pct: float,
    cyclical_market_value: float,
    cyclical_limit_pct: float,
    is_cyclical: bool,
    current_price: float,
) -> dict[str, Any]:
    constraints = [
        _add_constraint(
            constraint_id="single_position",
            label="单票上限",
            current_market_value=market_value,
            denominator=denominator,
            limit_pct=single_limit_pct,
        ),
        _add_constraint(
            constraint_id="industry",
            label=f"行业上限：{INDUSTRY_LABELS.get(industry, industry)}",
            current_market_value=industry_market_value,
            denominator=denominator,
            limit_pct=industry_limit_pct,
        ),
    ]
    if is_cyclical:
        constraints.append(
            _add_constraint(
                constraint_id="cyclical_total",
                label="强周期合计上限",
                current_market_value=cyclical_market_value,
                denominator=denominator,
                limit_pct=cyclical_limit_pct,
            )
        )

    finite_caps = [_to_float(item.get("max_add_market_value")) for item in constraints]
    strict_max = max(min(finite_caps), 0.0) if finite_caps else 0.0
    binding = [
        item
        for item in constraints
        if abs(_to_float(item.get("max_add_market_value")) - strict_max) <= 0.01
    ]
    if any(item.get("status") == "over_limit" for item in constraints):
        status = "over_limit"
    elif strict_max <= 0:
        status = "at_limit"
    elif any(item.get("status") == "near_limit" for item in constraints):
        status = "near_limit"
    else:
        status = "ok"

    max_shares = int(strict_max // current_price) if current_price > 0 else 0
    return {
        "status": status,
        "can_add": strict_max > 0 and status != "over_limit",
        "strict_max_add_market_value": round(strict_max, 2),
        "max_add_shares_estimate": max_shares,
        "max_add_round_lot_shares": (max_shares // 100) * 100,
        "price_basis": "current_price" if current_price > 0 else "missing",
        "constraints": constraints,
        "binding_constraints": binding,
        "formula": "(limit_pct * pool_market_value - current_constraint_market_value) / (1 - limit_pct)",
    }


def _add_constraint(
    *,
    constraint_id: str,
    label: str,
    current_market_value: float,
    denominator: float,
    limit_pct: float,
) -> dict[str, Any]:
    weight = _safe_ratio(current_market_value, denominator)
    max_add = _strict_add_capacity(
        current_market_value=current_market_value,
        denominator=denominator,
        limit_pct=limit_pct,
    )
    return {
        "constraint_id": constraint_id,
        "label": label,
        "current_market_value": round(current_market_value, 2),
        "current_weight": weight,
        "limit_pct": limit_pct,
        "status": _limit_status(weight, limit_pct),
        "max_add_market_value": round(max_add, 2),
    }


def _strict_add_capacity(*, current_market_value: float, denominator: float, limit_pct: float) -> float:
    if denominator <= 0 or limit_pct <= 0 or limit_pct >= 1:
        return 0.0
    numerator = limit_pct * denominator - current_market_value
    if numerator <= 0:
        return 0.0
    return numerator / (1 - limit_pct)


def _duplicate_symbol_groups(holdings: list[Holding]) -> list[dict[str, Any]]:
    groups: defaultdict[str, list[Holding]] = defaultdict(list)
    for holding in holdings:
        groups[_canonical_symbol(holding.symbol)].append(holding)
    duplicates = []
    for canonical, rows in sorted(groups.items()):
        if len(rows) > 1:
            duplicates.append(
                {
                    "canonical_symbol": canonical,
                    "positions": [_holding_identity(item) for item in rows],
                }
            )
    return duplicates


def _canonical_symbol(symbol: str) -> str:
    text = symbol.strip().upper()
    for suffix in (".SH", ".SZ", ".SS", ".US", ".HK"):
        if text.endswith(suffix):
            return text[: -len(suffix)]
    return text


def _canonical_us_symbol(symbol: str) -> str:
    text = symbol.strip().upper()
    base = text.split(".", 1)[0]
    return f"{base}.US"


def _is_us_income_symbol(symbol: str) -> bool:
    text = symbol.strip().upper()
    return text in US_INCOME_SYMBOLS or _canonical_us_symbol(text) in US_INCOME_SYMBOLS


def _market_group(market: str, symbol: str) -> str:
    clean_market = market.strip().upper()
    clean_symbol = symbol.strip().upper()
    if clean_market in {"US", "USA"} or clean_symbol.endswith(".US"):
        return "US"
    if clean_market in {"CN", "A", "ASHARE", "A_SHARE", "A股"} or clean_symbol.endswith((".SH", ".SZ", ".SS")):
        return "A股"
    if clean_market in {"HK", "港股"} or clean_symbol.endswith(".HK"):
        return "HK"
    return market.strip() or "UNKNOWN"


def _amount_rows(amounts: dict[str, float]) -> list[dict[str, Any]]:
    return [
        {"currency": currency, "amount": round(amount, 2)}
        for currency, amount in sorted(amounts.items())
        if currency
    ]


def _rounded_rows(rows: Any, *, amount_keys: set[str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        clean = dict(row)
        for key in amount_keys:
            if key in clean:
                clean[key] = round(float(clean[key] or 0), 2)
        result.append(clean)
    return result


def _write_us_distribution_history(records: list[USDistributionRecord]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with US_DISTRIBUTION_HISTORY_PATH.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "symbol",
                "ex_date",
                "payment_date",
                "record_date",
                "amount_per_share",
                "currency",
                "source",
                "notes",
            ],
        )
        writer.writeheader()
        for item in records:
            row = asdict(item)
            row["amount_per_share"] = _format_decimal(float(row["amount_per_share"]), 6)
            writer.writerow(row)


def _distribution_record_key(item: USDistributionRecord) -> tuple[str, str, str, str, float, str]:
    return (
        _canonical_us_symbol(item.symbol),
        _normalize_date_text(item.ex_date),
        _normalize_date_text(item.payment_date),
        _normalize_date_text(item.record_date),
        round(float(item.amount_per_share), 6),
        item.currency.upper(),
    )


def _distribution_effective_date(item: USDistributionRecord) -> str:
    return item.payment_date or item.ex_date or item.record_date or ""


def _distribution_effective_date_value(item: USDistributionRecord) -> date | None:
    value = _distribution_effective_date(item)
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _normalize_date_text(value: Any) -> str:
    text = str(value or "").strip().replace(".", "-").replace("/", "-")
    if not text:
        return ""
    parts = text.split()
    text = parts[0]
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        return text
    return parsed.isoformat()


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def _read_simple_key_value_yaml(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def _plan_float(data: dict[str, str], key: str, default: float) -> float:
    value = _to_float(data.get(key))
    return value if value > 0 else default


def _read_industry_limits(data: dict[str, str], default: dict[str, float]) -> dict[str, float]:
    result = dict(default)
    prefix = "limit_industry_"
    suffix = "_pct"
    for key, value in data.items():
        if not key.startswith(prefix) or not key.endswith(suffix):
            continue
        industry = key[len(prefix) : -len(suffix)].strip().lower()
        if not industry or industry == "default":
            continue
        limit = _to_float(value)
        if limit > 0:
            result[industry] = limit
    return result


def _read_csv_text_list(value: Any, default: list[str]) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return list(default)
    items = [
        item.strip().lower()
        for item in text.replace(";", ",").split(",")
        if item.strip()
    ]
    return items or list(default)


def _read_symbol_text_map(value: Any, default: dict[str, str]) -> dict[str, str]:
    result = dict(default)
    text = str(value or "").strip()
    if not text:
        return result
    for part in text.replace(";", ",").split(","):
        if "=" not in part:
            continue
        key, raw_value = part.split("=", 1)
        symbol = _canonical_symbol(key.strip())
        mapped = raw_value.strip().lower()
        if symbol and mapped:
            result[symbol] = mapped
    return result


def _format_text_list(items: list[str]) -> str:
    return ",".join(str(item).strip() for item in items if str(item).strip())


def _format_text_map(items: dict[str, str]) -> str:
    return ",".join(
        f"{key}={value}"
        for key, value in sorted(items.items())
        if str(key).strip() and str(value).strip()
    )


def _dedupe_text(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        text = str(item).strip()
        if text and text not in result:
            result.append(text)
    return result


def _missing_data_files() -> list[str]:
    files = [
        HOLDINGS_PATH,
        CAPITAL_FLOWS_PATH,
        PORTFOLIO_EVENTS_PATH,
        DIVIDEND_PLAN_PATH,
        US_DISTRIBUTION_HISTORY_PATH,
    ]
    return [str(path) for path in files if not path.exists()]


def _append_portfolio_event(event: PortfolioEvent) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    file_exists = PORTFOLIO_EVENTS_PATH.exists()
    with PORTFOLIO_EVENTS_PATH.open("a", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=["date", "event_type", "symbol", "shares", "price", "amount", "currency", "source", "notes"],
        )
        if not file_exists or PORTFOLIO_EVENTS_PATH.stat().st_size == 0:
            writer.writeheader()
        row = asdict(event)
        row["shares"] = _format_decimal(float(row["shares"]), 6)
        row["price"] = _format_decimal(float(row["price"]), 4)
        row["amount"] = _format_amount(float(row["amount"]))
        writer.writerow(row)


def _replace_holding(holdings: list[Holding], updated: Holding) -> None:
    rows: list[Holding] = []
    replaced = False
    for item in holdings:
        if item.symbol == updated.symbol:
            rows.append(updated)
            replaced = True
        else:
            rows.append(item)
    if not replaced:
        rows.append(updated)
    _write_holdings(rows)


def _find_holding(holdings: list[Holding], symbol: str) -> Holding | None:
    return next((item for item in holdings if item.symbol == symbol), None)


def _required_symbol(symbol: str) -> str:
    clean_symbol = symbol.strip()
    if not clean_symbol:
        raise ValueError("标的代码不能为空。")
    return clean_symbol


def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    text = str(value).strip().replace(",", "")
    if not text:
        return 0.0
    if text.endswith("%"):
        return float(text[:-1]) / 100
    return float(text)


def _safe_ratio(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 6)


def _parse_year(value: str) -> int | None:
    try:
        return datetime.fromisoformat(value).year
    except ValueError:
        return None


def _format_amount(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _format_decimal(value: float, places: int) -> str:
    return f"{value:.{places}f}".rstrip("0").rstrip(".")


def _money(value: Any, currency: str) -> str:
    amount = float(value or 0)
    return f"{amount:,.2f} {currency}"
