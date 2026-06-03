from __future__ import annotations

from src.longbridge_provider import fetch_longbridge_quotes
from src.market_data.models import MarketDataResult, error_result, ok_result
from src.market_data.symbol_mapper import to_longbridge_symbol


def fetch_longbridge_quote(symbol: str, timeout_seconds: int = 15) -> MarketDataResult:
    provider_symbol = to_longbridge_symbol(symbol)
    try:
        quotes = fetch_longbridge_quotes([provider_symbol], timeout_seconds=timeout_seconds)
        quote = quotes.get(provider_symbol.upper()) or quotes.get(provider_symbol.split(".", 1)[0].upper())
        if quote is None:
            return error_result(
                source="longbridge",
                market="US",
                symbol=symbol,
                error="Longbridge 未返回可用 quote。",
                data={"provider_symbol": provider_symbol},
            )
        return ok_result(
            source="longbridge",
            market="US",
            symbol=symbol,
            data={
                "requested_symbol": symbol,
                "provider_symbol": provider_symbol,
                "current_price": quote.current_price,
                "annual_dividend_per_share": 0.0,
                "dividend_status": "missing",
                "quote_source": quote.quote_source,
                "quote_timestamp": quote.timestamp,
                "currency": "USD",
            },
        )
    except Exception as exc:
        return error_result(
            source="longbridge",
            market="US",
            symbol=symbol,
            error=f"Longbridge quote 查询失败：{exc}",
            data={"provider_symbol": provider_symbol},
        )
