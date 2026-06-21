"""Longbridge capability allowlist and trading-write denylist."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Sequence


@dataclass(frozen=True)
class LongbridgeCapability:
    capability_id: str
    domain: str
    access: str
    description: str
    command_prefix: tuple[str, ...] = ()
    implemented: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


READ_CAPABILITIES: dict[str, LongbridgeCapability] = {
    "positions": LongbridgeCapability(
        capability_id="positions",
        domain="account",
        access="read",
        description="读取证券持仓。",
        command_prefix=("longbridge", "positions"),
        implemented=True,
    ),
    "watchlist": LongbridgeCapability(
        capability_id="watchlist",
        domain="watchlist",
        access="read",
        description="读取长桥自选股。",
        command_prefix=("longbridge", "watchlist"),
        implemented=True,
    ),
    "quote": LongbridgeCapability(
        capability_id="quote",
        domain="quote",
        access="read",
        description="读取证券报价。",
        command_prefix=("longbridge", "quote"),
        implemented=True,
    ),
    "cash_flow": LongbridgeCapability(
        capability_id="cash_flow",
        domain="account",
        access="read",
        description="读取账户资金流水。",
        command_prefix=("longbridge", "cash-flow"),
        implemented=True,
    ),
    "dividend": LongbridgeCapability(
        capability_id="dividend",
        domain="fundamental",
        access="read",
        description="读取分红/分配历史。",
        command_prefix=("longbridge", "dividend"),
        implemented=True,
    ),
    "exchange_rate": LongbridgeCapability(
        capability_id="exchange_rate",
        domain="account",
        access="read",
        description="读取汇率。",
        command_prefix=("longbridge", "exchange-rate"),
        implemented=True,
    ),
    "assets": LongbridgeCapability(
        capability_id="assets",
        domain="account",
        access="read",
        description="读取账户资产、现金、购买力和保证金概览。",
        command_prefix=("longbridge", "assets"),
        implemented=True,
    ),
    "portfolio": LongbridgeCapability(
        capability_id="portfolio",
        domain="account",
        access="read",
        description="读取组合总览、持仓、现金和盈亏。",
        command_prefix=("longbridge", "portfolio"),
        implemented=True,
    ),
    "order_history": LongbridgeCapability(
        capability_id="order_history",
        domain="execution_query",
        access="read",
        description="读取历史订单和委托状态。",
        command_prefix=("longbridge", "order"),
        implemented=True,
    ),
    "execution_history": LongbridgeCapability(
        capability_id="execution_history",
        domain="execution_query",
        access="read",
        description="读取历史成交。",
        command_prefix=("longbridge", "order", "executions"),
        implemented=True,
    ),
    "profit_analysis": LongbridgeCapability(
        capability_id="profit_analysis",
        domain="account",
        access="read",
        description="读取账户盈亏分析。",
        command_prefix=("longbridge", "profit-analysis"),
        implemented=True,
    ),
    "candles": LongbridgeCapability(
        capability_id="candles",
        domain="quote",
        access="read",
        description="读取 K 线和历史行情。",
    ),
    "market_state": LongbridgeCapability(
        capability_id="market_state",
        domain="quote",
        access="read",
        description="读取市场状态和交易日历。",
    ),
    "fundamentals": LongbridgeCapability(
        capability_id="fundamentals",
        domain="fundamental",
        access="read",
        description="读取公司资料、财报、估值、分红和行业数据。",
    ),
    "events": LongbridgeCapability(
        capability_id="events",
        domain="event",
        access="read",
        description="读取新闻、公告、公司事件、财报日历和分红日历。",
    ),
    "options_chain": LongbridgeCapability(
        capability_id="options_chain",
        domain="options",
        access="read",
        description="读取期权链、到期日、希腊值和隐含波动。",
    ),
}


DENIED_WRITE_CAPABILITIES: dict[str, LongbridgeCapability] = {
    "submit_order": LongbridgeCapability(
        capability_id="submit_order",
        domain="trade",
        access="write_forbidden",
        description="禁止自动下单。",
    ),
    "replace_order": LongbridgeCapability(
        capability_id="replace_order",
        domain="trade",
        access="write_forbidden",
        description="禁止自动改单。",
    ),
    "cancel_order": LongbridgeCapability(
        capability_id="cancel_order",
        domain="trade",
        access="write_forbidden",
        description="禁止自动撤单。",
    ),
    "conditional_order": LongbridgeCapability(
        capability_id="conditional_order",
        domain="trade",
        access="write_forbidden",
        description="禁止自动创建或修改条件单。",
    ),
    "recurring_order": LongbridgeCapability(
        capability_id="recurring_order",
        domain="trade",
        access="write_forbidden",
        description="禁止自动创建或修改定投单。",
    ),
    "option_order": LongbridgeCapability(
        capability_id="option_order",
        domain="trade",
        access="write_forbidden",
        description="禁止自动期权下单。",
    ),
    "broker_watchlist_write": LongbridgeCapability(
        capability_id="broker_watchlist_write",
        domain="watchlist",
        access="write_forbidden",
        description="禁止自动反写券商自选股。",
    ),
}

DENIED_COMMAND_TERMS = {
    "buy",
    "sell",
    "place-order",
    "submit-order",
    "replace-order",
    "modify-order",
    "buy",
    "sell",
    "cancel-order",
    "cancel",
    "replace",
    "conditional-order",
    "recurring-order",
    "option-order",
}


def list_read_capabilities(*, include_planned: bool = True) -> list[dict[str, object]]:
    items = READ_CAPABILITIES.values()
    if not include_planned:
        items = [item for item in items if item.implemented]
    return [item.to_dict() for item in items]


def list_denied_capabilities() -> list[dict[str, object]]:
    return [item.to_dict() for item in DENIED_WRITE_CAPABILITIES.values()]


def assert_read_capability(capability_id: str, *, require_implemented: bool = True) -> LongbridgeCapability:
    capability = READ_CAPABILITIES.get(capability_id)
    if capability is None:
        raise PermissionError(f"长桥能力未在只读 allowlist 中登记：{capability_id}")
    if capability.access != "read":
        raise PermissionError(f"长桥能力不是只读能力：{capability_id}")
    if require_implemented and not capability.implemented:
        raise PermissionError(f"长桥只读能力尚未实现固定 Provider：{capability_id}")
    return capability


def assert_longbridge_command_allowed(command: Sequence[str]) -> LongbridgeCapability:
    clean = tuple(str(part).strip() for part in command if str(part).strip())
    if len(clean) < 2 or clean[0] != "longbridge":
        raise PermissionError(f"不是允许的长桥命令：{' '.join(clean)}")

    lowered = {part.lower() for part in clean[1:]}
    denied = sorted(lowered & DENIED_COMMAND_TERMS)
    if denied:
        raise PermissionError(f"禁止执行长桥交易写命令：{', '.join(denied)}")

    matches = [
        capability
        for capability in READ_CAPABILITIES.values()
        if capability.implemented and capability.command_prefix and _starts_with(clean, capability.command_prefix)
    ]
    if matches:
        return max(matches, key=lambda item: len(item.command_prefix))
    raise PermissionError(f"长桥命令未在只读 allowlist 中登记：{' '.join(clean)}")


def _starts_with(command: tuple[str, ...], prefix: tuple[str, ...]) -> bool:
    return len(command) >= len(prefix) and command[: len(prefix)] == prefix
