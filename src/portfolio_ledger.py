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
        "template_files": {
            "holdings": str(TEMPLATE_DIR / "holdings.csv"),
            "capital_flows": str(TEMPLATE_DIR / "capital_flows.csv"),
            "dividend_plan": str(TEMPLATE_DIR / "dividend_plan.yaml"),
        },
    }


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
    files = [HOLDINGS_PATH, CAPITAL_FLOWS_PATH, DIVIDEND_PLAN_PATH]
    return [str(path) for path in files if not path.exists()]


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
