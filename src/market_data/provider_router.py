from __future__ import annotations

from collections.abc import Callable

from src.market_data.longbridge_market_provider import fetch_longbridge_quote
from src.market_data.models import MarketDataResult
from src.market_data.symbol_mapper import infer_market
from src.market_data.yahoo_provider import fetch_yahoo_quote
from src.market_phase import build_market_phase_context


ProviderCall = Callable[[str], MarketDataResult]


def fetch_quote(symbol: str, *, market: str | None = None) -> MarketDataResult:
    clean_market = (market or infer_market(symbol)).upper()
    if clean_market in {"CN", "A", "ASHARE", "A_SHARE"}:
        return _fetch_with_fallback(symbol, market="CN", providers=[("yfinance", lambda value: fetch_yahoo_quote(value, market="CN"))])
    if clean_market in {"US", "USA"}:
        return _fetch_with_fallback(
            symbol,
            market="US",
            providers=[
                ("longbridge", fetch_longbridge_quote),
                ("yfinance", lambda value: fetch_yahoo_quote(value, market="US")),
            ],
        )
    inferred = infer_market(symbol)
    return fetch_quote(symbol, market=inferred)


def fetch_market_data(symbol: str, *, market: str | None = None) -> dict[str, object]:
    return fetch_quote(symbol, market=market).to_dict()


def _fetch_with_fallback(
    symbol: str,
    *,
    market: str,
    providers: list[tuple[str, ProviderCall]],
) -> MarketDataResult:
    attempts: list[dict[str, object]] = []
    last_result: MarketDataResult | None = None
    phase = build_market_phase_context(market)
    for provider_name, provider in providers:
        result = provider(symbol)
        last_result = result
        attempts.append(
            {
                "provider": provider_name,
                "status": result.status,
                "error": result.error,
            }
        )
        if result.status == "ok":
            return _attach_quality(result, attempts=attempts, phase=phase)

    if last_result is None:
        raise RuntimeError("market data provider chain is empty")
    return _attach_quality(last_result, attempts=attempts, phase=phase)


def _attach_quality(
    result: MarketDataResult,
    *,
    attempts: list[dict[str, object]],
    phase: dict[str, object],
) -> MarketDataResult:
    data = dict(result.data)
    data["market_phase"] = phase
    limitations: list[str] = []
    coverage = {
        "quote": "ok" if result.status == "ok" and data.get("current_price") else "missing",
        "dividend": str(data.get("dividend_status") or "missing"),
        "market_phase": "ok",
    }
    if result.status != "ok":
        limitations.append(result.error or "行情数据源未返回可用结果。")
    if data.get("dividend_status") == "missing":
        limitations.append("行情源未返回可用股息字段；现金流判断仍必须使用财报、分配公告或到账流水。")
    for warning in phase.get("warnings") or []:
        limitations.append(str(warning))
    data_quality = {
        "source_chain": attempts,
        "freshness": "fresh" if result.status == "ok" else "unknown",
        "coverage": coverage,
        "limitations": _dedupe(limitations),
    }
    return MarketDataResult(
        status=result.status,
        source=result.source,
        market=result.market,
        symbol=result.symbol,
        data=data,
        error=result.error,
        source_chain=attempts,
        data_quality=data_quality,
    )


def _dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        if item and item not in result:
            result.append(item)
    return result
