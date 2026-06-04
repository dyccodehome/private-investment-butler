"""Longbridge read-only sync provider.

This module is the only place that may call the Longbridge CLI. The command is
fixed and read-only; callers cannot pass arbitrary shell text.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from typing import Any

from src.init import RUNTIME_DIR


LONGBRIDGE_POSITIONS_COMMAND = ["longbridge", "positions", "--format", "json"]
LONGBRIDGE_QUOTE_COMMAND_PREFIX = ["longbridge", "quote"]
LONGBRIDGE_CASH_FLOW_COMMAND_PREFIX = ["longbridge", "cash-flow"]
LONGBRIDGE_DIVIDEND_COMMAND_PREFIX = ["longbridge", "dividend"]
LONGBRIDGE_EXCHANGE_RATE_COMMAND = ["longbridge", "exchange-rate", "--format", "json"]
CASH_ANCHOR_SYMBOLS = {"QQQI", "QQQI.US", "XQQI", "XQQI.US", "TQQQ", "TQQQ.US"}
US_GROWTH_EXCLUDED_NOTE = "不属于 Cash Anchor 美股收益框架，保留给 Growth_Engine/US_Disruptive_Growth 或其他策略处理。"
LONGBRIDGE_CASH_FLOW_SOURCE = "longbridge_cash_flow"
LONGBRIDGE_DIVIDEND_HISTORY_SOURCE = "longbridge_dividend_history"


@dataclass(frozen=True)
class LongbridgePosition:
    """Normalized Longbridge stock position."""

    symbol: str
    name: str
    market: str
    currency: str
    quantity: float
    available_quantity: float
    cost_price: float
    account_channel: str = ""


@dataclass(frozen=True)
class LongbridgeQuote:
    """Normalized Longbridge quote."""

    symbol: str
    current_price: float
    quote_source: str
    timestamp: str = ""


@dataclass(frozen=True)
class LongbridgeCashFlow:
    """Normalized Longbridge account cash flow."""

    transaction_flow_name: str
    direction: str
    business_type: str
    balance: float
    currency: str
    business_time: str
    symbol: str
    description: str = ""
    flow_id: str = ""

    @property
    def event_date(self) -> date:
        return _parse_longbridge_business_date(self.business_time)


@dataclass(frozen=True)
class LongbridgeDividendRecord:
    """Normalized Longbridge per-share dividend/distribution history."""

    symbol: str
    amount_per_share: float
    currency: str
    ex_date: str = ""
    payment_date: str = ""
    record_date: str = ""
    description: str = ""


@dataclass(frozen=True)
class LongbridgeExchangeRate:
    """One Longbridge currency conversion rate."""

    base_currency: str
    other_currency: str
    average_rate: float
    bid_rate: float
    offer_rate: float


def sync_longbridge_positions(timeout_seconds: int = 15) -> dict[str, Any]:
    """Run the fixed Longbridge positions command and build a filtered proposal."""

    raw = _run_longbridge_positions(timeout_seconds=timeout_seconds)
    positions = parse_longbridge_positions(raw)
    proposal = build_cash_anchor_sync_proposal(positions)
    symbols = [item["symbol"] for item in proposal["included"]]
    quotes = fetch_longbridge_quotes(symbols, timeout_seconds=timeout_seconds) if symbols else {}
    _attach_quotes(proposal, quotes)
    return proposal


def sync_longbridge_us_income_distributions(
    *,
    start: date | None = None,
    end: date | None = None,
    timeout_seconds: int = 15,
) -> dict[str, Any]:
    """Sync actual USD distributions and historical per-share records for covered-call ETFs."""

    from src import portfolio_ledger

    current_date = end or date.today()
    start_date = start or date(current_date.year, 1, 1)
    holdings = portfolio_ledger.read_holdings()
    symbols = _cash_anchor_symbols_from_holdings(holdings)
    if not symbols:
        return {
            "source": "longbridge_cli",
            "scope": "us_income_distributions",
            "period": {"start": start_date.isoformat(), "end": current_date.isoformat()},
            "symbols": [],
            "cash_flow_import": {"created_count": 0, "duplicate_count": 0, "items": []},
            "history_import": {"created_count": 0, "updated_count": 0, "total_count": 0, "failures": []},
            "forecast": portfolio_ledger.build_portfolio_snapshot(as_of=current_date)["dividend_analysis"]["us_income_distribution_forecast"],
            "write_policy": "只写入分红到账事件和历史每份分配记录，不写入固定每股年分红。",
        }

    cash_flows = fetch_longbridge_cash_flows(start=start_date, end=current_date, timeout_seconds=timeout_seconds)
    dividend_flows = filter_dividend_cash_flows(cash_flows, symbols)
    cash_flow_import = import_longbridge_dividend_cash_flows(dividend_flows)

    history_records: list[LongbridgeDividendRecord] = []
    failures: list[dict[str, str]] = []
    for symbol in symbols:
        try:
            history_records.extend(fetch_longbridge_dividend_history(symbol, timeout_seconds=timeout_seconds))
        except RuntimeError as exc:
            failures.append({"symbol": symbol, "error": str(exc)})

    ledger_records = [
        portfolio_ledger.USDistributionRecord(
            symbol=item.symbol,
            ex_date=item.ex_date,
            payment_date=item.payment_date,
            record_date=item.record_date,
            amount_per_share=item.amount_per_share,
            currency=item.currency,
            source=LONGBRIDGE_DIVIDEND_HISTORY_SOURCE,
            notes=item.description,
        )
        for item in history_records
    ]
    history_import = portfolio_ledger.upsert_us_distribution_history(ledger_records)
    history_import["failures"] = failures

    snapshot = portfolio_ledger.build_portfolio_snapshot(as_of=current_date)
    return {
        "source": "longbridge_cli",
        "scope": "us_income_distributions",
        "period": {"start": start_date.isoformat(), "end": current_date.isoformat()},
        "symbols": symbols,
        "cash_flow_import": cash_flow_import,
        "history_import": history_import,
        "forecast": snapshot["dividend_analysis"]["us_income_distribution_forecast"],
        "write_policy": "只写入分红到账事件和历史每份分配记录，不写入固定每股年分红。",
    }


def parse_longbridge_positions(payload: str | dict[str, Any] | list[Any]) -> list[LongbridgePosition]:
    """Parse known Longbridge CLI/API positions JSON shapes."""

    data = json.loads(payload) if isinstance(payload, str) else payload
    rows = _extract_position_rows(data)
    positions: list[LongbridgePosition] = []
    for account_channel, row in rows:
        symbol = str(row.get("symbol") or "").strip()
        if not symbol:
            continue
        positions.append(
            LongbridgePosition(
                symbol=symbol,
                name=str(row.get("symbol_name") or row.get("name") or symbol).strip(),
                market=str(row.get("market") or "").strip(),
                currency=str(row.get("currency") or "USD").strip(),
                quantity=_to_float(row.get("quantity")),
                available_quantity=_to_float(row.get("available_quantity") or row.get("available")),
                cost_price=_to_float(row.get("cost_price")),
                account_channel=account_channel,
            )
        )
    return positions


def build_cash_anchor_sync_proposal(positions: list[LongbridgePosition]) -> dict[str, Any]:
    """Split Longbridge positions into Cash Anchor eligible and excluded holdings."""

    included = [item for item in positions if _is_cash_anchor_symbol(item.symbol)]
    excluded = [item for item in positions if not _is_cash_anchor_symbol(item.symbol)]
    return {
        "source": "longbridge_cli",
        "command": LONGBRIDGE_POSITIONS_COMMAND,
        "cash_anchor_symbols": sorted(CASH_ANCHOR_SYMBOLS),
        "included": [asdict(item) for item in included],
        "excluded": [
            {
                **asdict(item),
                "reason": US_GROWTH_EXCLUDED_NOTE,
            }
            for item in excluded
        ],
        "summary": {
            "total_positions": len(positions),
            "cash_anchor_positions": len(included),
            "excluded_positions": len(excluded),
        },
        "write_policy": "proposal_only",
    }


def format_longbridge_sync_proposal(proposal: dict[str, Any]) -> str:
    """Format a Longbridge sync proposal for Feishu/CLI."""

    summary = proposal["summary"]
    lines = [
        "长桥持仓同步提案：",
        f"- 总持仓数：{summary['total_positions']}",
        f"- Cash Anchor 可处理：{summary['cash_anchor_positions']}",
        f"- 已过滤其他策略持仓：{summary['excluded_positions']}",
        "- 写入策略：不直接覆盖账本；需要你确认后再写入。",
    ]
    included = proposal["included"]
    if included:
        lines.append("")
        lines.append("Cash Anchor 匹配持仓：")
        for item in included:
            current_price = item.get("current_price")
            current_text = (
                f"，当前价 {float(current_price):,.4f} {item['currency']}"
                if current_price not in (None, "")
                else "，当前价未取得"
            )
            lines.append(
                f"- {item['symbol']} {item['name']}：{item['quantity']:,.2f} 股，"
                f"成本价 {item['cost_price']:,.4f} {item['currency']}{current_text}"
            )
        lines.append("")
        lines.append("后续写入账本时，还需要补充 dividend=<每股年分红>；当前价会从长桥 quote 只读行情同步。")
    else:
        lines.append("")
        lines.append("未发现 QQQI、XQQI、TQQQ 持仓。")

    excluded = proposal["excluded"]
    if excluded:
        preview = ", ".join(item["symbol"] for item in excluded[:8])
        suffix = " ..." if len(excluded) > 8 else ""
        lines.append("")
        lines.append(f"已过滤持仓：{preview}{suffix}")
    return "\n".join(lines)


def apply_longbridge_cash_anchor_sync(timeout_seconds: int = 15) -> dict[str, Any]:
    """Apply Cash Anchor-eligible Longbridge positions to the local ledger.

    Dividend and tax fields are preserved. Current price is refreshed from the
    Longbridge read-only quote command when available. For newly discovered
    symbols without quote data, current price defaults to Longbridge cost price
    until the user records it explicitly.
    """

    proposal = sync_longbridge_positions(timeout_seconds=timeout_seconds)
    included = proposal["included"]
    if not included:
        return {
            "proposal": proposal,
            "updated": [],
            "skipped": [],
            "summary": {"updated_count": 0, "skipped_count": 0},
        }

    from src.portfolio_ledger import read_holdings, record_sync_event, upsert_holding

    existing = {item.symbol.upper(): item for item in read_holdings()}
    updated: list[dict[str, Any]] = []
    for item in included:
        symbol = str(item["symbol"]).upper()
        current = existing.get(symbol) or existing.get(symbol.split(".", 1)[0])
        quote_price = _to_float(item.get("current_price"))
        current_price = quote_price or (current.current_price if current else float(item["cost_price"]))
        dividend = current.annual_dividend_per_share if current else 0.0
        tax_rate = current.tax_rate if current else 0.0
        quote_note = f"; quote_source={item.get('quote_source')}" if item.get("quote_source") else ""
        notes = f"source=longbridge_cli; synced_at={datetime.now().replace(microsecond=0).isoformat()}{quote_note}"
        snapshot = upsert_holding(
            symbol=symbol,
            name=str(item["name"] or symbol),
            market=str(item["market"] or "US"),
            currency=str(item["currency"] or "USD"),
            shares=float(item["quantity"]),
            cost_price=float(item["cost_price"]),
            current_price=current_price,
            annual_dividend_per_share=dividend,
            tax_rate=tax_rate,
            notes=notes,
        )
        record_sync_event(
            symbol=symbol,
            shares=float(item["quantity"]),
            price=float(item["cost_price"]),
            amount=float(item["quantity"]) * float(item["cost_price"]),
            currency=str(item["currency"] or "USD"),
            source="longbridge_cli",
            notes=notes,
        )
        updated.append(
            {
                "symbol": symbol,
                "name": item["name"],
                "shares": float(item["quantity"]),
                "cost_price": float(item["cost_price"]),
                "current_price": current_price,
                "annual_dividend_per_share": dividend,
                "holding_action": snapshot.get("holding_action"),
            }
        )

    return {
        "proposal": proposal,
        "updated": updated,
        "skipped": proposal["excluded"],
        "summary": {"updated_count": len(updated), "skipped_count": len(proposal["excluded"])},
    }


def format_longbridge_apply_result(result: dict[str, Any]) -> str:
    """Format applied sync result."""

    summary = result["summary"]
    lines = [
        "长桥持仓已写入 Cash Anchor 账本：",
        f"- 已写入：{summary['updated_count']}",
        f"- 已过滤：{summary['skipped_count']}",
    ]
    if result["updated"]:
        lines.append("")
        lines.append("写入持仓：")
        for item in result["updated"]:
            lines.append(
                f"- {item['symbol']}：{item['shares']:,.2f} 股，成本价 {item['cost_price']:,.4f} USD，"
                f"当前价 {item['current_price']:,.4f} USD，每股年分红 {item['annual_dividend_per_share']:,.4f} USD"
            )
    lines.append("")
    lines.append("说明：当前价来自长桥 quote 只读行情；已有持仓保留每股年分红和税率；新持仓每股年分红为 0，后续可用 /holding 补充。")
    return "\n".join(lines)


def format_longbridge_us_income_result(result: dict[str, Any]) -> str:
    period = result.get("period") or {}
    cash_flow = result.get("cash_flow_import") or {}
    history = result.get("history_import") or {}
    forecast = result.get("forecast") or {}
    lines = [
        "长桥美元分配同步完成：",
        f"- 区间：{period.get('start')} 至 {period.get('end')}",
        f"- 覆盖标的：{', '.join(result.get('symbols') or []) or '无'}",
        f"- 到账分配：新增 {cash_flow.get('created_count', 0)} 笔，跳过重复 {cash_flow.get('duplicate_count', 0)} 笔",
        (
            f"- 历史每份分配：新增 {history.get('created_count', 0)} 条，"
            f"更新 {history.get('updated_count', 0)} 条，累计 {history.get('total_count', 0)} 条"
        ),
    ]
    failures = history.get("failures") or []
    if failures:
        lines.append("- 部分标的历史分配未取到：" + ", ".join(f"{item['symbol']}({item['error']})" for item in failures))

    positions = forecast.get("positions") or []
    if positions:
        lines.append("")
        lines.append("滚动预测：")
        for item in positions:
            three = item.get("trailing_3m") or {}
            six = item.get("trailing_6m") or {}
            twelve = item.get("trailing_12m") or {}
            currency = item.get("currency") or "USD"
            lines.append(
                f"- {item.get('symbol')}：近3个月年化约 {_money(three.get('estimated_annual_cash'), currency)}，"
                f"近6个月年化约 {_money(six.get('estimated_annual_cash'), currency)}，"
                f"近12个月口径约 {_money(twelve.get('estimated_annual_cash'), currency)}"
            )
    else:
        lines.append("")
        lines.append("暂时没有足够的美元分配历史，先只记录真实到账。")

    lines.append("")
    lines.append("口径：到账金额只认资金流水；滚动预测只看历史每份分配，不写成固定每股年分红。")
    return "\n".join(lines)


def fetch_longbridge_quotes(symbols: list[str], timeout_seconds: int = 15) -> dict[str, LongbridgeQuote]:
    """Fetch read-only Longbridge quotes for known symbols."""

    clean_symbols = [symbol.strip().upper() for symbol in symbols if symbol.strip()]
    if not clean_symbols:
        return {}
    raw = _run_longbridge_quote(clean_symbols, timeout_seconds=timeout_seconds)
    quotes = parse_longbridge_quotes(raw)
    return {quote.symbol.upper(): quote for quote in quotes}


def parse_longbridge_quotes(payload: str | list[Any] | dict[str, Any]) -> list[LongbridgeQuote]:
    """Parse Longbridge quote JSON and select the freshest usable price."""

    data = json.loads(payload) if isinstance(payload, str) else payload
    rows: list[Any]
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        body = data.get("data", data)
        rows = body if isinstance(body, list) else body.get("list", []) if isinstance(body, dict) else []
    else:
        rows = []

    quotes: list[LongbridgeQuote] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        price, source, timestamp = _select_current_quote_price(row)
        if price > 0:
            quotes.append(LongbridgeQuote(symbol=symbol, current_price=price, quote_source=source, timestamp=timestamp))
    return quotes


def fetch_longbridge_cash_flows(
    *,
    start: date,
    end: date,
    timeout_seconds: int = 15,
) -> list[LongbridgeCashFlow]:
    raw = _run_longbridge_cash_flow(start=start, end=end, timeout_seconds=timeout_seconds)
    return parse_longbridge_cash_flows(raw)


def parse_longbridge_cash_flows(payload: str | list[Any] | dict[str, Any]) -> list[LongbridgeCashFlow]:
    data = json.loads(payload) if isinstance(payload, str) else payload
    rows = _extract_list_rows(data)
    flows: list[LongbridgeCashFlow] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or row.get("stock_code") or "").strip().upper()
        balance = _to_float(row.get("balance") or row.get("amount"))
        if not symbol or balance == 0:
            continue
        flows.append(
            LongbridgeCashFlow(
                transaction_flow_name=str(
                    row.get("transaction_flow_name")
                    or row.get("flow_name")
                    or row.get("name")
                    or ""
                ).strip(),
                direction=str(row.get("direction") or "").strip(),
                business_type=str(row.get("business_type") or "").strip(),
                balance=balance,
                currency=str(row.get("currency") or "USD").strip().upper(),
                business_time=str(row.get("business_time") or row.get("time") or row.get("date") or "").strip(),
                symbol=symbol,
                description=str(row.get("description") or row.get("desc") or "").strip(),
                flow_id=str(row.get("id") or row.get("flow_id") or row.get("transaction_id") or "").strip(),
            )
        )
    return flows


def filter_dividend_cash_flows(
    flows: list[LongbridgeCashFlow],
    symbols: list[str],
) -> list[LongbridgeCashFlow]:
    allowed = {_normalize_us_symbol(item) for item in symbols}
    result: list[LongbridgeCashFlow] = []
    for flow in flows:
        if _normalize_us_symbol(flow.symbol) not in allowed:
            continue
        if flow.balance <= 0:
            continue
        if not _looks_like_dividend_flow(flow):
            continue
        result.append(flow)
    return result


def import_longbridge_dividend_cash_flows(flows: list[LongbridgeCashFlow]) -> dict[str, Any]:
    from src import portfolio_ledger

    existing = {
        _portfolio_event_key(item)
        for item in portfolio_ledger.read_portfolio_events()
        if item.event_type == "dividend" and item.source == LONGBRIDGE_CASH_FLOW_SOURCE
    }
    created: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    for flow in flows:
        key = _cash_flow_event_key(flow)
        item = {
            "date": flow.event_date.isoformat(),
            "symbol": flow.symbol,
            "amount": round(flow.balance, 2),
            "currency": flow.currency,
            "flow_name": flow.transaction_flow_name,
        }
        if key in existing:
            duplicates.append(item)
            continue
        notes = _longbridge_cash_flow_notes(flow)
        portfolio_ledger.record_dividend(
            symbol=flow.symbol,
            amount=flow.balance,
            dividend_date=flow.event_date,
            currency=flow.currency,
            source=LONGBRIDGE_CASH_FLOW_SOURCE,
            notes=notes,
        )
        existing.add(key)
        created.append(item)
    return {
        "created_count": len(created),
        "duplicate_count": len(duplicates),
        "items": created,
        "duplicates": duplicates,
    }


def fetch_longbridge_dividend_history(
    symbol: str,
    *,
    timeout_seconds: int = 15,
) -> list[LongbridgeDividendRecord]:
    provider_symbol = _normalize_us_symbol(symbol)
    raw = _run_longbridge_dividend(provider_symbol, timeout_seconds=timeout_seconds)
    return parse_longbridge_dividend_history(raw, symbol=provider_symbol)


def fetch_longbridge_exchange_rates(timeout_seconds: int = 15) -> list[LongbridgeExchangeRate]:
    raw = _run_longbridge_exchange_rate(timeout_seconds=timeout_seconds)
    return parse_longbridge_exchange_rates(raw)


def parse_longbridge_exchange_rates(payload: str | list[Any] | dict[str, Any]) -> list[LongbridgeExchangeRate]:
    data = json.loads(payload) if isinstance(payload, str) else payload
    rows = _extract_list_rows(data)
    rates: list[LongbridgeExchangeRate] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        base_currency = str(row.get("base_currency") or row.get("base") or "").strip().upper()
        other_currency = str(row.get("other_currency") or row.get("other") or "").strip().upper()
        average_rate = _to_float(row.get("average_rate") or row.get("rate"))
        if not base_currency or not other_currency or average_rate <= 0:
            continue
        rates.append(
            LongbridgeExchangeRate(
                base_currency=base_currency,
                other_currency=other_currency,
                average_rate=average_rate,
                bid_rate=_to_float(row.get("bid_rate")),
                offer_rate=_to_float(row.get("offer_rate")),
            )
        )
    return rates


def parse_longbridge_dividend_history(
    payload: str | list[Any] | dict[str, Any],
    *,
    symbol: str,
) -> list[LongbridgeDividendRecord]:
    data = json.loads(payload) if isinstance(payload, str) else payload
    rows = _extract_list_rows(data)
    records: list[LongbridgeDividendRecord] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        desc = str(row.get("desc") or row.get("description") or row.get("content") or "").strip()
        amount, currency = _parse_dividend_amount(row, desc)
        if amount <= 0:
            continue
        records.append(
            LongbridgeDividendRecord(
                symbol=str(row.get("symbol") or symbol).strip().upper(),
                amount_per_share=amount,
                currency=currency or "USD",
                ex_date=_normalize_date_text(row.get("ex_date") or row.get("ex_dividend_date")),
                payment_date=_normalize_date_text(row.get("payment_date") or row.get("pay_date")),
                record_date=_normalize_date_text(row.get("record_date")),
                description=desc,
            )
        )
    return records


def _run_longbridge_positions(timeout_seconds: int) -> str:
    try:
        result = subprocess.run(
            LONGBRIDGE_POSITIONS_COMMAND,
            check=False,
            capture_output=True,
            text=True,
            env=_longbridge_env(),
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("未找到 longbridge CLI。请先安装并执行 longbridge auth login。") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("longbridge positions 执行超时。") from exc

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"longbridge positions 执行失败：{detail or result.returncode}")
    return result.stdout


def _run_longbridge_quote(symbols: list[str], timeout_seconds: int) -> str:
    command = [*LONGBRIDGE_QUOTE_COMMAND_PREFIX, *symbols, "--format", "json"]
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            env=_longbridge_env(),
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("未找到 longbridge CLI。请先安装并执行 longbridge auth login。") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("longbridge quote 执行超时。") from exc

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"longbridge quote 执行失败：{detail or result.returncode}")
    return result.stdout


def _run_longbridge_cash_flow(*, start: date, end: date, timeout_seconds: int) -> str:
    command = [
        *LONGBRIDGE_CASH_FLOW_COMMAND_PREFIX,
        "--start",
        start.isoformat(),
        "--end",
        end.isoformat(),
        "--format",
        "json",
    ]
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            env=_longbridge_env(),
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("未找到 longbridge CLI。请先安装并执行 longbridge auth login。") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("longbridge cash-flow 执行超时。") from exc

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"longbridge cash-flow 执行失败：{detail or result.returncode}")
    return result.stdout


def _run_longbridge_dividend(symbol: str, *, timeout_seconds: int) -> str:
    command = [*LONGBRIDGE_DIVIDEND_COMMAND_PREFIX, symbol, "--format", "json"]
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            env=_longbridge_env(),
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("未找到 longbridge CLI。请先安装并执行 longbridge auth login。") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"longbridge dividend {symbol} 执行超时。") from exc

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"longbridge dividend {symbol} 执行失败：{detail or result.returncode}")
    return result.stdout


def _run_longbridge_exchange_rate(*, timeout_seconds: int) -> str:
    try:
        result = subprocess.run(
            LONGBRIDGE_EXCHANGE_RATE_COMMAND,
            check=False,
            capture_output=True,
            text=True,
            env=_longbridge_env(),
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("未找到 longbridge CLI。请先安装 longbridge。") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("longbridge exchange-rate 执行超时。") from exc

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"longbridge exchange-rate 执行失败：{detail or result.returncode}")
    return result.stdout


def _longbridge_env() -> dict[str, str]:
    env = dict(os.environ)
    log_dir = RUNTIME_DIR / "longbridge_cli_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    env.setdefault("LONGBRIDGE_LOG_PATH", str(log_dir))
    return env


def _attach_quotes(proposal: dict[str, Any], quotes: dict[str, LongbridgeQuote]) -> None:
    for item in proposal["included"]:
        symbol = str(item["symbol"]).upper()
        quote = quotes.get(symbol) or quotes.get(symbol.split(".", 1)[0])
        if quote is None:
            item["current_price"] = None
            item["quote_source"] = ""
            item["quote_timestamp"] = ""
            continue
        item["current_price"] = quote.current_price
        item["quote_source"] = quote.quote_source
        item["quote_timestamp"] = quote.timestamp


def _select_current_quote_price(row: dict[str, Any]) -> tuple[float, str, str]:
    candidates: list[tuple[datetime, float, str, str]] = []
    for key in ("pre_market_quote", "post_market_quote", "overnight_quote"):
        nested = row.get(key)
        if not isinstance(nested, dict):
            continue
        price = _to_float(nested.get("last"))
        timestamp_text = str(nested.get("timestamp") or "")
        timestamp = _parse_quote_timestamp(timestamp_text)
        if price > 0 and timestamp is not None:
            candidates.append((timestamp, price, key, timestamp_text))
    if candidates:
        _, price, source, timestamp = max(candidates, key=lambda item: item[0])
        return price, source, timestamp

    price = _to_float(row.get("last") or row.get("last_done") or row.get("prev_close"))
    return price, "last", ""


def _parse_quote_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _extract_position_rows(data: Any) -> list[tuple[str, dict[str, Any]]]:
    if isinstance(data, dict):
        body = data.get("data", data)
        if isinstance(body, dict) and isinstance(body.get("list"), list):
            rows: list[tuple[str, dict[str, Any]]] = []
            for account in body["list"]:
                if not isinstance(account, dict):
                    continue
                account_channel = str(account.get("account_channel") or "")
                stock_info = account.get("stock_info")
                if isinstance(stock_info, list):
                    rows.extend((account_channel, item) for item in stock_info if isinstance(item, dict))
            return rows
        for key in ("positions", "stock_info", "items"):
            value = body.get(key) if isinstance(body, dict) else None
            if isinstance(value, list):
                return [("", item) for item in value if isinstance(item, dict)]
    if isinstance(data, list):
        return [("", item) for item in data if isinstance(item, dict)]
    raise ValueError("无法解析 Longbridge positions JSON。")


def _extract_list_rows(data: Any) -> list[Any]:
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    body = data.get("data", data)
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("list", "items", "rows", "data"):
            value = body.get(key)
            if isinstance(value, list):
                return value
        for value in body.values():
            rows = _extract_list_rows(value)
            if rows:
                return rows
    return []


def _is_cash_anchor_symbol(symbol: str) -> bool:
    normalized = symbol.strip().upper()
    base = normalized.split(".", 1)[0]
    return normalized in CASH_ANCHOR_SYMBOLS or base in CASH_ANCHOR_SYMBOLS


def _cash_anchor_symbols_from_holdings(holdings: list[Any]) -> list[str]:
    symbols = {
        _normalize_us_symbol(str(item.symbol))
        for item in holdings
        if getattr(item, "shares", 0) > 0 and _is_cash_anchor_symbol(str(item.symbol))
    }
    return sorted(symbols)


def _normalize_us_symbol(symbol: str) -> str:
    text = symbol.strip().upper()
    base = text.split(".", 1)[0]
    return f"{base}.US"


def _looks_like_dividend_flow(flow: LongbridgeCashFlow) -> bool:
    text = f"{flow.transaction_flow_name} {flow.description}".lower()
    keywords = (
        "dividend",
        "distribution",
        "div",
        "股息",
        "分红",
        "派息",
        "派发",
        "分配",
    )
    return any(keyword in text for keyword in keywords)


def _portfolio_event_key(event: Any) -> tuple[str, str, str, float, str]:
    return (
        str(event.date),
        _normalize_us_symbol(str(event.symbol)),
        str(event.currency).upper(),
        round(float(event.amount or 0), 2),
        LONGBRIDGE_CASH_FLOW_SOURCE,
    )


def _cash_flow_event_key(flow: LongbridgeCashFlow) -> tuple[str, str, str, float, str]:
    return (
        flow.event_date.isoformat(),
        _normalize_us_symbol(flow.symbol),
        flow.currency.upper(),
        round(float(flow.balance or 0), 2),
        LONGBRIDGE_CASH_FLOW_SOURCE,
    )


def _longbridge_cash_flow_notes(flow: LongbridgeCashFlow) -> str:
    parts = [
        f"flow_name={flow.transaction_flow_name}",
        f"business_time={flow.business_time}",
        f"description={flow.description}",
    ]
    if flow.flow_id:
        parts.append(f"flow_id={flow.flow_id}")
    return "; ".join(part for part in parts if part and not part.endswith("="))


def _parse_longbridge_business_date(value: str) -> date:
    text = str(value or "").strip()
    if not text:
        return date.today()
    if text.isdigit():
        return datetime.fromtimestamp(int(text), tz=timezone.utc).date()
    normalized = text.replace(".", "-").replace("/", "-")
    try:
        return datetime.fromisoformat(normalized.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        return date.fromisoformat(normalized.split()[0])
    except ValueError:
        return date.today()


def _parse_dividend_amount(row: dict[str, Any], desc: str) -> tuple[float, str]:
    for amount_key in ("amount_per_share", "cash_amount", "dividend", "cash_dividend"):
        amount = _to_float(row.get(amount_key))
        if amount > 0:
            return amount, str(row.get("currency") or "USD").strip().upper()

    text = desc.strip()
    currency = str(row.get("currency") or "").strip().upper()
    currency_pattern = r"(USD|HKD|CNY|CNH|SGD)"
    patterns = [
        rf"{currency_pattern}\s*([0-9]+(?:\.[0-9]+)?)\s*(?:/|per)?\s*(?:share|股)?",
        rf"([0-9]+(?:\.[0-9]+)?)\s*{currency_pattern}",
        r"每股(?:派息|派发|分配|股息|现金红利)?\s*([0-9]+(?:\.[0-9]+)?)\s*(USD|HKD|CNY|CNH|SGD)?",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        groups = [item for item in match.groups() if item]
        amount = next((_to_float(item) for item in groups if _to_float(item) > 0), 0.0)
        found_currency = next((item.upper() for item in groups if item.upper() in {"USD", "HKD", "CNY", "CNH", "SGD"}), "")
        if amount > 0:
            return amount, found_currency or currency or "USD"
    return 0.0, currency or "USD"


def _normalize_date_text(value: Any) -> str:
    text = str(value or "").strip().replace(".", "-").replace("/", "-")
    if not text:
        return ""
    try:
        return date.fromisoformat(text.split()[0]).isoformat()
    except ValueError:
        return text


def _money(value: Any, currency: str) -> str:
    amount = _to_float(value)
    return f"{amount:,.2f} {currency}"


def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    text = str(value).strip().replace(",", "")
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0
