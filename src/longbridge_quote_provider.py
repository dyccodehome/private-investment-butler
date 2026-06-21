"""Longbridge read-only quote, kline and market-status provider."""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict
from datetime import date, datetime, timedelta
from typing import Any, Sequence

from src.longbridge_capabilities import assert_longbridge_command_allowed, assert_read_capability
from src.longbridge_provider import parse_longbridge_quotes, longbridge_env


READ_ONLY_WRITE_POLICY = "read_only_market_data; no order placement, amendment, or cancellation"
DEFAULT_KLINE_PERIOD = "day"
DEFAULT_KLINE_COUNT = 140
DEFAULT_KLINE_SYMBOL_LIMIT = 6
DEFAULT_QUOTE_SYMBOL_LIMIT = 30
VALID_KLINE_PERIODS = {"1m", "5m", "15m", "30m", "1h", "day", "week", "month", "year"}
VALID_MARKETS = {"US", "HK", "CN", "SG", "SH", "SZ"}


def fetch_realtime_quotes(symbols: list[str], *, timeout_seconds: int = 15) -> dict[str, Any]:
    """Fetch real-time quotes for a bounded symbol list."""

    clean_symbols = _clean_symbols(symbols)
    command = ["longbridge", "quote", *clean_symbols, "--format", "json"]
    if not clean_symbols:
        return _provider_payload(scope="quotes", command=[], data={}, summary={"quote_count": 0})
    payload = _run_json_command("quote", command, timeout_seconds=timeout_seconds)
    quotes = {quote.symbol.upper(): asdict(quote) for quote in parse_longbridge_quotes(payload)}
    return _provider_payload(
        scope="quotes",
        command=command,
        data=quotes,
        summary={"requested_symbol_count": len(clean_symbols), "quote_count": len(quotes)},
    )


def fetch_kline(
    symbol: str,
    *,
    period: str = DEFAULT_KLINE_PERIOD,
    count: int = DEFAULT_KLINE_COUNT,
    adjust: str | None = None,
    timeout_seconds: int = 15,
) -> dict[str, Any]:
    """Fetch recent K lines for one symbol."""

    clean_symbol = _clean_symbol(symbol)
    clean_period = _clean_period(period)
    clean_count = max(1, min(300, int(count or DEFAULT_KLINE_COUNT)))
    command = ["longbridge", "kline", clean_symbol, "--period", clean_period, "--count", str(clean_count)]
    _append_optional_adjust(command, adjust)
    command.extend(["--format", "json"])
    payload = _run_json_command("candles", command, timeout_seconds=timeout_seconds)
    rows = _normalize_kline_rows(payload)
    return _provider_payload(
        scope="kline",
        command=command,
        data={"symbol": clean_symbol, "period": clean_period, "rows": rows, "technical": _technical_summary(rows)},
        summary={"symbol": clean_symbol, "period": clean_period, "kline_count": len(rows)},
    )


def fetch_kline_history(
    symbol: str,
    *,
    start: date | str,
    end: date | str,
    period: str = DEFAULT_KLINE_PERIOD,
    adjust: str | None = None,
    timeout_seconds: int = 15,
) -> dict[str, Any]:
    """Fetch historical K lines for one symbol and date window."""

    clean_symbol = _clean_symbol(symbol)
    clean_start = _parse_date(start)
    clean_end = _parse_date(end)
    clean_period = _clean_period(period)
    command = [
        "longbridge",
        "kline",
        "history",
        clean_symbol,
        "--period",
        clean_period,
        "--start",
        clean_start.isoformat(),
        "--end",
        clean_end.isoformat(),
    ]
    _append_optional_adjust(command, adjust)
    command.extend(["--format", "json"])
    payload = _run_json_command("candles", command, timeout_seconds=timeout_seconds)
    rows = _normalize_kline_rows(payload)
    return _provider_payload(
        scope="kline_history",
        command=command,
        data={"symbol": clean_symbol, "period": clean_period, "rows": rows, "technical": _technical_summary(rows)},
        summary={
            "symbol": clean_symbol,
            "period": clean_period,
            "start": clean_start.isoformat(),
            "end": clean_end.isoformat(),
            "kline_count": len(rows),
        },
    )


def fetch_market_status(*, timeout_seconds: int = 15) -> dict[str, Any]:
    """Fetch current market statuses."""

    command = ["longbridge", "market-status", "--format", "json"]
    payload = _run_json_command("market_state", command, timeout_seconds=timeout_seconds)
    rows = _extract_rows(payload)
    return _provider_payload(
        scope="market_status",
        command=command,
        data=rows,
        summary={"market_count": len(rows)},
    )


def fetch_trading_sessions(*, timeout_seconds: int = 15) -> dict[str, Any]:
    """Fetch trading session definitions."""

    command = ["longbridge", "trading", "session", "--format", "json"]
    payload = _run_json_command("trading_calendar", command, timeout_seconds=timeout_seconds)
    rows = _extract_rows(payload)
    return _provider_payload(
        scope="trading_sessions",
        command=command,
        data=rows,
        summary={"market_count": len(rows)},
    )


def fetch_trading_days(
    *,
    market: str = "US",
    start: date | str | None = None,
    end: date | str | None = None,
    timeout_seconds: int = 15,
) -> dict[str, Any]:
    """Fetch trading days for one market."""

    clean_market = _clean_market(market)
    command = ["longbridge", "trading", "days", clean_market]
    clean_start = _parse_date(start) if start else None
    clean_end = _parse_date(end) if end else None
    if clean_start:
        command.extend(["--start", clean_start.isoformat()])
    if clean_end:
        command.extend(["--end", clean_end.isoformat()])
    command.extend(["--format", "json"])
    payload = _run_json_command("trading_calendar", command, timeout_seconds=timeout_seconds)
    trading_days, half_days = _trading_day_lists(payload)
    return _provider_payload(
        scope="trading_days",
        command=command,
        data={"market": clean_market, "raw": payload, "trading_days": trading_days, "half_trading_days": half_days},
        summary={
            "market": clean_market,
            "trading_day_count": len(trading_days),
            "half_trading_day_count": len(half_days),
        },
    )


def fetch_market_temperature(
    *,
    market: str = "US",
    start: date | str | None = None,
    end: date | str | None = None,
    timeout_seconds: int = 15,
) -> dict[str, Any]:
    """Fetch current or historical Longbridge market temperature."""

    clean_market = _clean_market(market)
    command = ["longbridge", "market-temp", clean_market]
    clean_start = _parse_date(start) if start else None
    clean_end = _parse_date(end) if end else None
    if clean_start or clean_end:
        command.append("--history")
    if clean_start:
        command.extend(["--start", clean_start.isoformat()])
    if clean_end:
        command.extend(["--end", clean_end.isoformat()])
    command.extend(["--format", "json"])
    payload = _run_json_command("market_temperature", command, timeout_seconds=timeout_seconds)
    return _provider_payload(
        scope="market_temperature",
        command=command,
        data=payload,
        summary=_market_temperature_summary(payload, clean_market),
    )


def build_market_context_snapshot(
    *,
    symbols: list[str],
    market: str = "US",
    as_of: date | None = None,
    quote_symbol_limit: int = DEFAULT_QUOTE_SYMBOL_LIMIT,
    kline_symbol_limit: int = DEFAULT_KLINE_SYMBOL_LIMIT,
    kline_count: int = DEFAULT_KLINE_COUNT,
    timeout_seconds: int = 15,
) -> dict[str, Any]:
    """Build a partial-tolerant market context for scheduled reviews."""

    clean_market = _clean_market(market)
    clean_symbols = _clean_symbols(symbols)[: max(1, quote_symbol_limit)]
    kline_symbols = clean_symbols[: max(0, kline_symbol_limit)]
    target_date = as_of or date.today()
    calendar_start = target_date - timedelta(days=7)
    calendar_end = target_date + timedelta(days=7)
    sections: dict[str, Any] = {}
    source_chain: list[dict[str, Any]] = []

    def collect(name: str, fetcher: Any) -> None:
        try:
            payload = fetcher()
        except RuntimeError as exc:
            source_chain.append({"provider": "longbridge_cli", "scope": name, "status": "error", "error": str(exc)})
            sections[name] = {"status": "error", "error": str(exc), "data": None}
            return
        source_chain.append({"provider": "longbridge_cli", "scope": name, "status": "ok", "error": ""})
        sections[name] = payload

    collect("market_status", lambda: fetch_market_status(timeout_seconds=timeout_seconds))
    collect(
        "trading_days",
        lambda: fetch_trading_days(
            market=clean_market,
            start=calendar_start,
            end=calendar_end,
            timeout_seconds=timeout_seconds,
        ),
    )
    collect("trading_sessions", lambda: fetch_trading_sessions(timeout_seconds=timeout_seconds))
    collect("market_temperature", lambda: fetch_market_temperature(market=clean_market, timeout_seconds=timeout_seconds))
    collect("quotes", lambda: fetch_realtime_quotes(clean_symbols, timeout_seconds=timeout_seconds))
    klines: dict[str, Any] = {}
    for symbol in kline_symbols:
        try:
            klines[symbol] = fetch_kline(symbol, count=kline_count, timeout_seconds=timeout_seconds)
            source_chain.append({"provider": "longbridge_cli", "scope": f"kline:{symbol}", "status": "ok", "error": ""})
        except RuntimeError as exc:
            source_chain.append(
                {"provider": "longbridge_cli", "scope": f"kline:{symbol}", "status": "error", "error": str(exc)}
            )
            klines[symbol] = {"status": "error", "error": str(exc), "data": None}
    sections["klines"] = klines

    warnings = [str(item.get("error")) for item in source_chain if item.get("status") != "ok" and item.get("error")]
    status = "ok" if not warnings else "partial"
    symbol_data = _build_symbol_market_data(sections)
    return {
        "source": "longbridge_cli",
        "scope": "market_context_snapshot",
        "as_of": _now_iso(),
        "market": clean_market,
        "symbols": clean_symbols,
        "kline_symbols": kline_symbols,
        "sections": sections,
        "symbol_data": symbol_data,
        "summary": _market_context_summary(sections, symbol_data),
        "data_quality": {
            "status": status,
            "source_chain": source_chain,
            "limitations": warnings,
            "kline_symbol_limit": kline_symbol_limit,
            "quote_symbol_limit": quote_symbol_limit,
        },
        "write_policy": READ_ONLY_WRITE_POLICY,
    }


def format_market_context_snapshot(snapshot: dict[str, Any]) -> str:
    """Format a market context snapshot for CLI/Feishu."""

    summary = snapshot.get("summary") or {}
    quality = snapshot.get("data_quality") or {}
    lines = [
        "长桥行情只读快照",
        f"- 市场：{snapshot.get('market')}",
        f"- 状态：{quality.get('status') or 'unknown'}",
        f"- 覆盖标的：{summary.get('symbol_count', 0)}",
        f"- Quote 成功：{summary.get('quote_count', 0)}",
        f"- K线成功：{summary.get('kline_symbol_count', 0)}",
        f"- 市场状态条目：{summary.get('market_status_count', 0)}",
        f"- 交易日条目：{summary.get('trading_day_count', 0)}",
        f"- 写入策略：{snapshot.get('write_policy')}",
    ]
    symbol_data = snapshot.get("symbol_data") if isinstance(snapshot.get("symbol_data"), dict) else {}
    if symbol_data:
        lines.extend(["", "标的摘要："])
        for symbol, item in list(symbol_data.items())[:10]:
            quote = item.get("quote") if isinstance(item, dict) else {}
            technical = item.get("technical") if isinstance(item, dict) else {}
            lines.append(
                f"- {symbol}：price={quote.get('current_price') or 'NA'}，"
                f"MA120={technical.get('ma120') or 'NA'}，trend={technical.get('ma120_relation') or 'unknown'}"
            )
    limitations = list(quality.get("limitations") or [])
    if limitations:
        lines.extend(["", "数据缺口："])
        lines.extend(f"- {item}" for item in limitations[:8])
    return "\n".join(lines)


def _run_json_command(capability_id: str, command: Sequence[str], *, timeout_seconds: int) -> Any:
    assert_read_capability(capability_id)
    assert_longbridge_command_allowed(command)
    try:
        completed = subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            env=longbridge_env(),
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("未找到 longbridge CLI。请先安装并执行 longbridge auth login。") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{' '.join(command)} 执行超时。") from exc

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"{' '.join(command)} 执行失败：{detail or completed.returncode}")
    try:
        return json.loads(completed.stdout or "null")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{' '.join(command)} 返回非 JSON 输出。") from exc


def _provider_payload(*, scope: str, command: list[str], data: Any, summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "longbridge_cli",
        "scope": scope,
        "as_of": _now_iso(),
        "command": command,
        "status": "ok",
        "data": data,
        "summary": summary,
        "write_policy": READ_ONLY_WRITE_POLICY,
    }


def _build_symbol_market_data(sections: dict[str, Any]) -> dict[str, Any]:
    quotes_section = sections.get("quotes") if isinstance(sections.get("quotes"), dict) else {}
    quotes = quotes_section.get("data") if isinstance(quotes_section.get("data"), dict) else {}
    klines = sections.get("klines") if isinstance(sections.get("klines"), dict) else {}
    result: dict[str, Any] = {}
    for symbol, quote in quotes.items():
        if not isinstance(quote, dict):
            continue
        result.setdefault(symbol, {})["quote"] = quote
    for symbol, payload in klines.items():
        if not isinstance(payload, dict) or payload.get("status") == "error":
            continue
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        result.setdefault(symbol, {})["technical"] = data.get("technical") or {}
        rows = data.get("rows") if isinstance(data.get("rows"), list) else []
        result[symbol]["kline_preview"] = rows[-5:]
    return result


def _market_context_summary(sections: dict[str, Any], symbol_data: dict[str, Any]) -> dict[str, Any]:
    market_status = _section_summary(sections, "market_status")
    trading_days = _section_summary(sections, "trading_days")
    quotes = _section_summary(sections, "quotes")
    klines = sections.get("klines") if isinstance(sections.get("klines"), dict) else {}
    return {
        "symbol_count": len(symbol_data),
        "quote_count": quotes.get("quote_count", 0),
        "kline_symbol_count": sum(1 for item in klines.values() if isinstance(item, dict) and item.get("status") != "error"),
        "market_status_count": market_status.get("market_count", 0),
        "trading_day_count": trading_days.get("trading_day_count", 0),
    }


def _section_summary(sections: dict[str, Any], key: str) -> dict[str, Any]:
    section = sections.get(key) if isinstance(sections.get(key), dict) else {}
    summary = section.get("summary") if isinstance(section.get("summary"), dict) else {}
    return summary


def _normalize_kline_rows(payload: Any) -> list[dict[str, Any]]:
    rows = _extract_rows(payload)
    result: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        result.append(
            {
                "time": str(row.get("time") or row.get("timestamp") or row.get("date") or ""),
                "open": _to_float(row.get("open")),
                "high": _to_float(row.get("high")),
                "low": _to_float(row.get("low")),
                "close": _to_float(row.get("close")),
                "volume": _to_float(row.get("volume")),
                "turnover": _to_float(row.get("turnover") or row.get("amount")),
            }
        )
    return [item for item in result if item["close"] > 0]


def _technical_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    closes = [_to_float(item.get("close")) for item in rows if _to_float(item.get("close")) > 0]
    latest_close = closes[-1] if closes else 0.0
    ma20 = _moving_average(closes, 20)
    ma50 = _moving_average(closes, 50)
    ma120 = _moving_average(closes, 120)
    relation = "unknown"
    if latest_close and ma120:
        relation = "above_ma120" if latest_close >= ma120 else "below_ma120"
    return {
        "latest_close": latest_close,
        "ma20": ma20,
        "ma50": ma50,
        "ma120": ma120,
        "ma120_relation": relation,
        "kline_count": len(closes),
    }


def _moving_average(values: list[float], window: int) -> float:
    if not values:
        return 0.0
    usable = values[-min(window, len(values)) :]
    return round(sum(usable) / len(usable), 6)


def _extract_rows(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    body = payload.get("data", payload)
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("list", "items", "rows", "klines", "candles", "markets"):
            value = body.get(key)
            if isinstance(value, list):
                return value
        nested = body.get("data")
        if nested is not body:
            return _extract_rows(nested)
    return []


def _trading_day_lists(payload: Any) -> tuple[list[str], list[str]]:
    body = payload.get("data", payload) if isinstance(payload, dict) else payload
    if not isinstance(body, dict):
        return [], []
    trading_days = [str(item) for item in body.get("trading_days") or body.get("days") or []]
    half_days = [str(item) for item in body.get("half_trading_days") or body.get("half_days") or []]
    return trading_days, half_days


def _market_temperature_summary(payload: Any, market: str) -> dict[str, Any]:
    if isinstance(payload, list):
        return {"market": market, "history_count": len(payload)}
    body = payload.get("data", payload) if isinstance(payload, dict) else {}
    if not isinstance(body, dict):
        return {"market": market}
    return {
        "market": str(body.get("market") or market),
        "temperature": _to_float(body.get("temperature")),
        "valuation": _to_float(body.get("valuation")),
        "sentiment": _to_float(body.get("sentiment")),
        "description": str(body.get("description") or ""),
    }


def _append_optional_adjust(command: list[str], adjust: str | None) -> None:
    clean = str(adjust or "").strip().lower()
    if clean:
        command.extend(["--adjust", clean])


def _clean_symbols(symbols: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for symbol in symbols:
        clean = _clean_symbol(symbol)
        if clean and clean not in seen:
            result.append(clean)
            seen.add(clean)
    return result


def _clean_symbol(symbol: str) -> str:
    raw = str(symbol or "").strip().upper()
    if not raw:
        raise ValueError("symbol 不能为空。")
    if raw.endswith(".US"):
        return raw
    if "." not in raw:
        return raw + ".US"
    return raw


def _clean_period(period: str) -> str:
    clean = str(period or DEFAULT_KLINE_PERIOD).strip().lower()
    if clean not in VALID_KLINE_PERIODS:
        raise ValueError(f"不支持的 K 线周期：{period}")
    return clean


def _clean_market(market: str) -> str:
    clean = str(market or "US").strip().upper()
    if clean in {"A", "ASHARE", "A_SHARE"}:
        clean = "CN"
    if clean not in VALID_MARKETS:
        raise ValueError(f"不支持的市场：{market}")
    return clean


def _parse_date(value: date | str) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _to_float(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()
