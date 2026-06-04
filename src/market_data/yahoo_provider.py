from __future__ import annotations

from typing import Any

from src.market_data.models import MarketDataResult, error_result, ok_result
from src.market_data.symbol_mapper import infer_market, to_yahoo_symbol


def fetch_yahoo_quote(symbol: str, *, market: str | None = None) -> MarketDataResult:
    yahoo_symbol = to_yahoo_symbol(symbol)
    clean_market = (market or infer_market(symbol)).upper()
    try:
        yf = _import_yfinance()
        ticker = yf.Ticker(yahoo_symbol)
        info = getattr(ticker, "fast_info", None) or {}
        history = ticker.history(period="1mo", auto_adjust=False)
        current_price = _extract_price(info, history)
        dividend = _extract_annual_dividend(ticker, info)
        data = {
            "requested_symbol": symbol,
            "provider_symbol": yahoo_symbol,
            "current_price": current_price,
            "annual_dividend_per_share": dividend,
            "currency": str(_safe_get(info, "currency") or ("USD" if clean_market == "US" else "CNY")),
            "price_status": "ok" if current_price > 0 else "missing",
            "dividend_status": "ok" if dividend > 0 else "missing",
        }
        if current_price <= 0:
            return error_result(
                source="yfinance",
                market=clean_market,
                symbol=symbol,
                data=data,
                error="Yahoo Finance 未返回可用最新价。",
            )
        return ok_result(source="yfinance", market=clean_market, symbol=symbol, data=data)
    except ImportError:
        return error_result(
            source="yfinance",
            market=clean_market,
            symbol=symbol,
            error="未安装 yfinance。请先安装依赖：pip install yfinance。",
            data={"provider_symbol": yahoo_symbol},
        )
    except Exception as exc:
        return error_result(
            source="yfinance",
            market=clean_market,
            symbol=symbol,
            error=f"Yahoo Finance 查询失败：{exc}",
            data={"provider_symbol": yahoo_symbol},
        )


def _import_yfinance() -> Any:
    import yfinance as yf

    return yf


def _extract_price(info: Any, history: Any) -> float:
    for key in ("last_price", "lastPrice", "regular_market_price"):
        value = _safe_get(info, key)
        price = _to_float(value)
        if price > 0:
            return price
    try:
        if history is not None and not history.empty:
            return _to_float(history["Close"].dropna().iloc[-1])
    except Exception:
        return 0.0
    return 0.0


def _extract_annual_dividend(ticker: Any, info: Any) -> float:
    for key in ("last_dividend_value", "lastDividendValue"):
        value = _safe_get(info, key)
        dividend = _to_float(value)
        if dividend > 0:
            return dividend
    try:
        dividends = ticker.dividends
        if dividends is not None and len(dividends) > 0:
            recent = dividends.dropna().tail(12)
            return round(sum(float(item) for item in recent), 6)
    except Exception:
        return 0.0
    return 0.0


def _safe_get(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    text = str(value).strip().replace(",", "")
    if not text or text.lower() in {"nan", "none"}:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0
