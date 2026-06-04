"""Resolve which strategy island currently owns a known local symbol."""

from __future__ import annotations

from typing import Iterable


def framework_for_known_holding(symbol: str | None) -> str | None:
    """Return the framework that has ``symbol`` in its local holdings."""

    key = _symbol_key(symbol)
    if not key:
        return None
    if key in _cash_anchor_symbol_keys():
        return "Cash_Anchor"
    if key in _growth_engine_symbol_keys():
        return "Growth_Engine"
    return None


def symbol_in_framework(symbol: str | None, framework_id: str | None) -> bool:
    if not framework_id:
        return False
    return framework_for_known_holding(symbol) == framework_id


def _cash_anchor_symbol_keys() -> set[str]:
    try:
        from src.portfolio_ledger import read_holdings

        return _symbol_keys(item.symbol for item in read_holdings())
    except Exception:
        return set()


def _growth_engine_symbol_keys() -> set[str]:
    try:
        from src.growth_portfolio import read_growth_holdings

        return _symbol_keys(item.symbol for item in read_growth_holdings())
    except Exception:
        return set()


def _symbol_keys(symbols: Iterable[str]) -> set[str]:
    keys: set[str] = set()
    for symbol in symbols:
        key = _symbol_key(symbol)
        if key:
            keys.add(key)
    return keys


def _symbol_key(symbol: str | None) -> str:
    clean = str(symbol or "").strip().upper()
    for suffix in (".SH", ".SZ", ".SS", ".US"):
        if clean.endswith(suffix):
            clean = clean[: -len(suffix)]
            break
    return clean
