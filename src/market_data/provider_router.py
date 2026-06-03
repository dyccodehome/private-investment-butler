from __future__ import annotations

from src.market_data.longbridge_market_provider import fetch_longbridge_quote
from src.market_data.models import MarketDataResult
from src.market_data.symbol_mapper import infer_market
from src.market_data.yahoo_provider import fetch_yahoo_quote


def fetch_quote(symbol: str, *, market: str | None = None) -> MarketDataResult:
    clean_market = (market or infer_market(symbol)).upper()
    if clean_market in {"CN", "A", "ASHARE", "A_SHARE"}:
        return fetch_yahoo_quote(symbol)
    if clean_market in {"US", "USA"}:
        return fetch_longbridge_quote(symbol)
    return fetch_yahoo_quote(symbol) if infer_market(symbol) == "CN" else fetch_longbridge_quote(symbol)


def fetch_market_data(symbol: str, *, market: str | None = None) -> dict[str, object]:
    return fetch_quote(symbol, market=market).to_dict()
