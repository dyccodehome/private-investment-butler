"""Cash_Anchor 本地持仓账本与退休分红进度计算。

本模块只做确定性读写和计算，不调用 LLM。它让现金流策略里的“分红能力、
成本股息率、年度投入进度、退休目标缺口”有可审计的数据来源。
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, asdict
from datetime import date, datetime
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
class DividendPlan:
    """现金流退休计划的核心目标参数。"""

    plan_name: str = "Cash Anchor 10 Year Retirement Plan"
    base_year: int = 2026
    retirement_years: int = 10
    annual_contribution_target: float = 0.0
    target_annual_dividend: float = 0.0
    currency: str = "CNY"


def build_portfolio_snapshot(as_of: date | None = None) -> dict[str, Any]:
    """读取本地账本并返回现金流策略快照。"""

    current_date = as_of or date.today()
    holdings = read_holdings()
    flows = read_capital_flows()
    plan = read_dividend_plan()
    positions = [_position_metrics(item) for item in holdings]

    total_cost = sum(item["cost_basis"] for item in positions)
    total_market_value = sum(item["market_value"] for item in positions)
    gross_annual_dividend = sum(item["gross_annual_dividend"] for item in positions)
    net_annual_dividend = sum(item["net_annual_dividend"] for item in positions)
    current_year_contribution = sum(
        flow.amount for flow in flows if _parse_year(flow.date) == current_date.year
    )

    return {
        "as_of": current_date.isoformat(),
        "data_files": {
            "holdings": str(HOLDINGS_PATH),
            "capital_flows": str(CAPITAL_FLOWS_PATH),
            "portfolio_events": str(PORTFOLIO_EVENTS_PATH),
            "dividend_plan": str(DIVIDEND_PLAN_PATH),
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
            "current_year_contribution": round(current_year_contribution, 2),
            "annual_contribution_progress": _safe_ratio(
                current_year_contribution,
                plan.annual_contribution_target,
            ),
            "annual_dividend_progress": _safe_ratio(
                net_annual_dividend,
                plan.target_annual_dividend,
            ),
            "annual_contribution_gap": round(
                max(plan.annual_contribution_target - current_year_contribution, 0),
                2,
            ),
            "annual_dividend_gap": round(
                max(plan.target_annual_dividend - net_annual_dividend, 0),
                2,
            ),
        },
        "positions": positions,
        "capital_flows": [asdict(item) for item in flows],
        "portfolio_events": [asdict(item) for item in read_portfolio_events()],
        "template_files": {
            "holdings": str(TEMPLATE_DIR / "holdings.csv"),
            "capital_flows": str(TEMPLATE_DIR / "capital_flows.csv"),
            "dividend_plan": str(TEMPLATE_DIR / "dividend_plan.yaml"),
        },
    }


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
    target_annual_dividend: float | None = None,
    currency: str | None = None,
    plan_name: str | None = None,
    base_year: int | None = None,
    retirement_years: int | None = None,
    as_of: date | None = None,
) -> dict[str, Any]:
    """更新退休现金流计划目标，并返回更新后的快照。"""

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
        target_annual_dividend=(
            target_annual_dividend
            if target_annual_dividend is not None
            else current.target_annual_dividend
        ),
        currency=currency or current.currency,
    )
    if updated.annual_contribution_target < 0:
        raise ValueError("年度投入目标不能为负数。")
    if updated.target_annual_dividend < 0:
        raise ValueError("目标年分红不能为负数。")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DIVIDEND_PLAN_PATH.write_text(
        "\n".join(
            [
                f"plan_name: {updated.plan_name}",
                f"base_year: {updated.base_year}",
                f"retirement_years: {updated.retirement_years}",
                f"annual_contribution_target: {_format_amount(updated.annual_contribution_target)}",
                f"target_annual_dividend: {_format_amount(updated.target_annual_dividend)}",
                f"currency: {updated.currency}",
                "",
            ]
        ),
        encoding="utf-8",
    )
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
            source="manual",
            notes=notes,
        )
    )
    return {
        "date": target_date.isoformat(),
        "symbol": clean_symbol,
        "amount": amount,
        "currency": currency,
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
    """格式化目标更新后的年度进度。"""

    plan = snapshot["plan"]
    summary = snapshot["summary"]
    currency = plan["currency"]
    return (
        "已更新 Cash Anchor 目标：\n"
        f"- 年度工资投入目标：{_money(plan['annual_contribution_target'], currency)}\n"
        f"- 目标年分红：{_money(plan['target_annual_dividend'], currency)}\n"
        f"- 今年已投入：{_money(summary['current_year_contribution'], currency)}\n"
        f"- 投入完成进度：{float(summary['annual_contribution_progress'] or 0):.1%}\n"
        f"- 今年投入缺口：{_money(summary['annual_contribution_gap'], currency)}\n"
        f"- 当前净年分红能力：{_money(summary['net_annual_dividend'], currency)}\n"
        f"- 分红目标进度：{float(summary['annual_dividend_progress'] or 0):.1%}\n"
        f"- 分红目标缺口：{_money(summary['annual_dividend_gap'], currency)}\n"
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
    return (
        f"{action}持仓：{holding['symbol']} {holding['name']}\n"
        f"- 份额：{holding['shares']:,.2f}\n"
        f"- 成本价：{_money(holding['cost_price'], currency)}\n"
        f"- 当前价：{_money(holding['current_price'], currency)}\n"
        f"- 单位年分红：{_money(holding['annual_dividend_per_share'], currency)}\n"
        f"- 该持仓预估税前年分红：{_money(gross, currency)}\n"
        f"- 该持仓预估税后年分红：{_money(net, currency)}\n"
        f"- 组合预估税后年分红：{_money(summary['net_annual_dividend'], currency)}\n"
        f"- 分红目标进度：{float(summary['annual_dividend_progress'] or 0):.1%}\n"
        f"- 分红目标缺口：{_money(summary['annual_dividend_gap'], currency)}\n"
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
        f"- 分红目标进度：{float(summary['annual_dividend_progress'] or 0):.1%}\n"
        f"- 事件账本：{snapshot['event_path']}"
    )


def format_sell_progress(snapshot: dict[str, Any]) -> str:
    summary = snapshot["summary"]
    currency = snapshot["plan"]["currency"]
    return (
        f"已记录卖出：{snapshot['sold_symbol']}\n"
        f"- 剩余份额：{snapshot['remaining_shares']:,.2f}\n"
        f"- 组合预估税后年分红：{_money(summary['net_annual_dividend'], currency)}\n"
        f"- 分红目标进度：{float(summary['annual_dividend_progress'] or 0):.1%}\n"
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
    return (
        "Cash Anchor 持仓快照：\n"
        f"- 持仓数量：{summary['holding_count']}\n"
        f"- 总成本：{_money(summary['total_cost'], currency)}\n"
        f"- 当前市值：{_money(summary['total_market_value'], currency)}\n"
        f"- 预估税后年分红：{_money(summary['net_annual_dividend'], currency)}\n"
        f"- 成本税后股息率：{float(summary['net_yield_on_cost'] or 0):.2%}\n"
        f"- 当前年投入：{_money(summary['current_year_contribution'], currency)}\n"
        f"- 投入目标进度：{float(summary['annual_contribution_progress'] or 0):.1%}\n"
        f"- 分红目标进度：{float(summary['annual_dividend_progress'] or 0):.1%}\n"
        f"- 持仓账本：{snapshot['data_files']['holdings']}\n"
        f"- 事件账本：{snapshot['data_files']['portfolio_events']}"
    )


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


def read_dividend_plan() -> DividendPlan:
    """读取 `data/dividend_plan.yaml`；缺失时返回空目标。"""

    if not DIVIDEND_PLAN_PATH.exists():
        return DividendPlan()
    data = _read_simple_key_value_yaml(DIVIDEND_PLAN_PATH)
    return DividendPlan(
        plan_name=str(data.get("plan_name") or "Cash Anchor 10 Year Retirement Plan"),
        base_year=int(_to_float(data.get("base_year")) or 2026),
        retirement_years=int(_to_float(data.get("retirement_years")) or 10),
        annual_contribution_target=_to_float(data.get("annual_contribution_target")),
        target_annual_dividend=_to_float(data.get("target_annual_dividend")),
        currency=str(data.get("currency") or "CNY"),
    )


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
                        "target_annual_dividend: 115000",
                        "currency: CNY",
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


def _missing_data_files() -> list[str]:
    files = [HOLDINGS_PATH, CAPITAL_FLOWS_PATH, PORTFOLIO_EVENTS_PATH, DIVIDEND_PLAN_PATH]
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
