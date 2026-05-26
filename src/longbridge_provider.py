"""Longbridge read-only sync provider.

This module is the only place that may call the Longbridge CLI. The command is
fixed and read-only; callers cannot pass arbitrary shell text.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


LONGBRIDGE_POSITIONS_COMMAND = ["longbridge", "positions", "--format", "json"]
CASH_ANCHOR_SYMBOLS = {"QQQI", "QQQI.US", "XQQI", "XQQI.US", "TQQQ", "TQQQ.US"}
US_GROWTH_EXCLUDED_NOTE = "不属于 Cash Anchor 美股收益框架，保留给 Growth_Engine/US_Disruptive_Growth 或其他策略处理。"


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


def sync_longbridge_positions(timeout_seconds: int = 15) -> dict[str, Any]:
    """Run the fixed Longbridge positions command and build a filtered proposal."""

    raw = _run_longbridge_positions(timeout_seconds=timeout_seconds)
    positions = parse_longbridge_positions(raw)
    return build_cash_anchor_sync_proposal(positions)


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
            lines.append(
                f"- {item['symbol']} {item['name']}：{item['quantity']:,.2f} 股，"
                f"成本价 {item['cost_price']:,.4f} {item['currency']}"
            )
        lines.append("")
        lines.append("后续写入账本时，还需要补充 current=<当前价> 和 dividend=<每股年分红>。")
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

    Existing current price, dividend and tax fields are preserved. For newly
    discovered symbols, current price defaults to Longbridge cost price and
    dividend/tax default to 0 until the user records them explicitly.
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
        current_price = current.current_price if current else float(item["cost_price"])
        dividend = current.annual_dividend_per_share if current else 0.0
        tax_rate = current.tax_rate if current else 0.0
        notes = f"source=longbridge_cli; synced_at={datetime.now().replace(microsecond=0).isoformat()}"
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
    lines.append("说明：已有持仓保留当前价、每股年分红和税率；新持仓的当前价暂用成本价，每股年分红为 0，后续可用 /holding 补充。")
    return "\n".join(lines)


def _run_longbridge_positions(timeout_seconds: int) -> str:
    try:
        result = subprocess.run(
            LONGBRIDGE_POSITIONS_COMMAND,
            check=False,
            capture_output=True,
            text=True,
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


def _is_cash_anchor_symbol(symbol: str) -> bool:
    normalized = symbol.strip().upper()
    base = normalized.split(".", 1)[0]
    return normalized in CASH_ANCHOR_SYMBOLS or base in CASH_ANCHOR_SYMBOLS


def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    text = str(value).strip().replace(",", "")
    if not text:
        return 0.0
    return float(text)
