"""Longbridge read-only US options data provider."""

from __future__ import annotations

import json
import subprocess
from datetime import date, datetime
from typing import Any, Sequence

from src.longbridge_capabilities import assert_longbridge_command_allowed, assert_read_capability
from src.longbridge_provider import longbridge_env


READ_ONLY_WRITE_POLICY = "read_only_options_data; no option order placement, exercise, amendment, or cancellation"
DEFAULT_SYMBOL_LIMIT = 6
DEFAULT_CHAIN_SYMBOL_LIMIT = 3
DEFAULT_DAILY_COUNT = 30
DEFAULT_CHAIN_PREVIEW_LIMIT = 20
DEFAULT_QUOTE_CONTRACT_LIMIT = 4
MAX_DAILY_COUNT = 120
MAX_CONTRACT_QUOTES = 20
VALID_MARKETS = {"US", "HK", "CN", "SG", "SH", "SZ"}


def fetch_option_expirations(symbol: str, *, timeout_seconds: int = 15) -> dict[str, Any]:
    clean_symbol = _clean_symbol(symbol)
    command = ["longbridge", "option", "chain", clean_symbol, "--format", "json"]
    payload = _run_json_command("option_chain", command, timeout_seconds=timeout_seconds)
    expirations = _extract_expirations(payload)
    return _provider_payload(
        scope="option_expirations",
        command=command,
        data={"raw": payload, "expirations": expirations},
        summary={"symbol": clean_symbol, "expiration_count": len(expirations), "nearest_expiration": expirations[0] if expirations else ""},
    )


def fetch_option_chain(symbol: str, expiry_date: date | str, *, timeout_seconds: int = 15) -> dict[str, Any]:
    clean_symbol = _clean_symbol(symbol)
    clean_date = _clean_date(expiry_date)
    command = ["longbridge", "option", "chain", clean_symbol, "--date", clean_date, "--format", "json"]
    payload = _run_json_command("option_chain", command, timeout_seconds=timeout_seconds)
    rows = _compact_chain_rows(payload, limit=DEFAULT_CHAIN_PREVIEW_LIMIT)
    return _provider_payload(
        scope="option_chain",
        command=command,
        data={"symbol": clean_symbol, "expiry_date": clean_date, "raw": payload, "rows": rows},
        summary={"symbol": clean_symbol, "expiry_date": clean_date, "strike_count": _count_rows(payload)},
    )


def fetch_option_quotes(option_symbols: list[str], *, timeout_seconds: int = 15) -> dict[str, Any]:
    clean_symbols = _clean_contract_symbols(option_symbols)[:MAX_CONTRACT_QUOTES]
    if not clean_symbols:
        return _provider_payload(scope="option_quotes", command=[], data={}, summary={"quote_count": 0})
    command = ["longbridge", "option", "quote", *clean_symbols, "--format", "json"]
    payload = _run_json_command("option_quote", command, timeout_seconds=timeout_seconds)
    rows = _compact_quote_rows(payload)
    return _provider_payload(
        scope="option_quotes",
        command=command,
        data={"raw": payload, "quotes": rows},
        summary={"requested_contract_count": len(clean_symbols), "quote_count": len(rows)},
    )


def fetch_option_volume(symbol: str, *, timeout_seconds: int = 15) -> dict[str, Any]:
    clean_symbol = _clean_symbol(symbol)
    command = ["longbridge", "option", "volume", clean_symbol, "--format", "json"]
    payload = _run_json_command("option_volume", command, timeout_seconds=timeout_seconds)
    return _provider_payload(
        scope="option_volume",
        command=command,
        data=payload,
        summary=_option_volume_summary(payload, clean_symbol),
    )


def fetch_option_volume_daily(symbol: str, *, count: int = DEFAULT_DAILY_COUNT, timeout_seconds: int = 15) -> dict[str, Any]:
    clean_symbol = _clean_symbol(symbol)
    clean_count = max(1, min(MAX_DAILY_COUNT, int(count or DEFAULT_DAILY_COUNT)))
    command = ["longbridge", "option", "volume", "daily", clean_symbol, "--count", str(clean_count), "--format", "json"]
    payload = _run_json_command("option_volume", command, timeout_seconds=timeout_seconds)
    rows = _compact_volume_daily_rows(payload, limit=clean_count)
    return _provider_payload(
        scope="option_volume_daily",
        command=command,
        data={"raw": payload, "rows": rows},
        summary={"symbol": clean_symbol, "daily_count": len(rows), "latest_pc_vol": rows[0].get("pc_vol") if rows else 0},
    )


def build_options_context_snapshot(
    *,
    symbols: list[str],
    market: str = "US",
    symbol_limit: int = DEFAULT_SYMBOL_LIMIT,
    chain_symbol_limit: int = DEFAULT_CHAIN_SYMBOL_LIMIT,
    daily_count: int = DEFAULT_DAILY_COUNT,
    include_chain: bool = True,
    include_quotes: bool = False,
    timeout_seconds: int = 15,
) -> dict[str, Any]:
    """Build a partial-tolerant options risk snapshot for scheduled reviews."""

    clean_market = _clean_market(market)
    clean_symbols = _clean_symbols(symbols)[: max(1, symbol_limit)]
    chain_symbols = clean_symbols[: max(0, chain_symbol_limit)] if include_chain else []
    clean_daily_count = max(1, min(MAX_DAILY_COUNT, int(daily_count or DEFAULT_DAILY_COUNT)))
    sections: dict[str, dict[str, Any]] = {}
    source_chain: list[dict[str, Any]] = []

    for symbol in clean_symbols:
        symbol_sections: dict[str, Any] = {}

        def collect(name: str, fetcher: Any) -> None:
            try:
                payload = fetcher()
            except RuntimeError as exc:
                source_chain.append({"provider": "longbridge_cli", "scope": f"{name}:{symbol}", "status": "error", "error": str(exc)})
                symbol_sections[name] = {"status": "error", "error": str(exc), "data": None}
                return
            source_chain.append({"provider": "longbridge_cli", "scope": f"{name}:{symbol}", "status": "ok", "error": ""})
            symbol_sections[name] = payload

        collect("expirations", lambda symbol=symbol: fetch_option_expirations(symbol, timeout_seconds=timeout_seconds))
        collect("volume", lambda symbol=symbol: fetch_option_volume(symbol, timeout_seconds=timeout_seconds))
        collect(
            "volume_daily",
            lambda symbol=symbol: fetch_option_volume_daily(symbol, count=clean_daily_count, timeout_seconds=timeout_seconds),
        )
        if symbol in chain_symbols:
            expiration_payload = symbol_sections.get("expirations") if isinstance(symbol_sections.get("expirations"), dict) else {}
            nearest_expiration = _nearest_expiration_from_provider_payload(expiration_payload)
            if nearest_expiration:
                collect(
                    "chain",
                    lambda symbol=symbol, expiry=nearest_expiration: fetch_option_chain(
                        symbol,
                        expiry,
                        timeout_seconds=timeout_seconds,
                    ),
                )
                if include_quotes:
                    contracts = _contract_symbols_from_chain(symbol_sections.get("chain") or {})[:DEFAULT_QUOTE_CONTRACT_LIMIT]
                    if contracts:
                        collect("quotes", lambda contracts=contracts: fetch_option_quotes(contracts, timeout_seconds=timeout_seconds))
        sections[symbol] = symbol_sections

    warnings = [str(item.get("error")) for item in source_chain if item.get("status") != "ok" and item.get("error")]
    status = "ok" if not warnings else "partial"
    symbol_data = {
        symbol: _compact_symbol_options(sections.get(symbol) or {})
        for symbol in clean_symbols
    }
    return {
        "source": "longbridge_cli",
        "scope": "options_context_snapshot",
        "as_of": _now_iso(),
        "market": clean_market,
        "symbols": clean_symbols,
        "chain_symbols": chain_symbols,
        "sections": sections,
        "symbol_data": symbol_data,
        "summary": _options_context_summary(symbol_data),
        "data_quality": {
            "status": status,
            "source_chain": source_chain,
            "limitations": warnings,
            "symbol_limit": symbol_limit,
            "chain_symbol_limit": chain_symbol_limit,
            "daily_count": clean_daily_count,
            "include_quotes": include_quotes,
        },
        "write_policy": READ_ONLY_WRITE_POLICY,
    }


def format_options_context_snapshot(snapshot: dict[str, Any]) -> str:
    summary = snapshot.get("summary") or {}
    quality = snapshot.get("data_quality") or {}
    lines = [
        "长桥期权只读快照",
        f"- 市场：{snapshot.get('market')}",
        f"- 状态：{quality.get('status') or 'unknown'}",
        f"- 覆盖底层：{summary.get('symbol_count', 0)}",
        f"- 到期日可用：{summary.get('symbols_with_expirations', 0)}",
        f"- 期权链可用：{summary.get('symbols_with_chain', 0)}",
        f"- 成交量可用：{summary.get('symbols_with_volume', 0)}",
        f"- 高 put/call 风险：{summary.get('high_put_call_count', 0)}",
        f"- 写入策略：{snapshot.get('write_policy')}",
    ]
    symbol_data = snapshot.get("symbol_data") if isinstance(snapshot.get("symbol_data"), dict) else {}
    if symbol_data:
        lines.extend(["", "底层摘要："])
        for symbol, item in list(symbol_data.items())[:10]:
            if not isinstance(item, dict):
                continue
            risk = item.get("risk_summary") if isinstance(item.get("risk_summary"), dict) else {}
            lines.append(
                f"- {symbol}：expiry={item.get('nearest_expiration') or 'NA'}，"
                f"pc_vol={risk.get('latest_pc_vol') or 'NA'}，"
                f"signal={risk.get('put_call_signal') or 'unknown'}，"
                f"strikes={item.get('strike_count', 0)}"
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


def _compact_symbol_options(sections: dict[str, Any]) -> dict[str, Any]:
    expirations_payload = sections.get("expirations") if isinstance(sections.get("expirations"), dict) else {}
    chain_payload = sections.get("chain") if isinstance(sections.get("chain"), dict) else {}
    volume_payload = sections.get("volume") if isinstance(sections.get("volume"), dict) else {}
    daily_payload = sections.get("volume_daily") if isinstance(sections.get("volume_daily"), dict) else {}
    quotes_payload = sections.get("quotes") if isinstance(sections.get("quotes"), dict) else {}

    expirations = _nearest_expirations(expirations_payload, limit=12)
    chain_rows = _provider_data_rows(chain_payload, key="rows")
    daily_rows = _provider_data_rows(daily_payload, key="rows")
    quote_rows = _provider_data_rows(quotes_payload, key="quotes")
    return {
        "expirations": expirations,
        "nearest_expiration": expirations[0] if expirations else "",
        "chain_preview": chain_rows[:DEFAULT_CHAIN_PREVIEW_LIMIT],
        "strike_count": _summary_number(chain_payload, "strike_count"),
        "volume_snapshot": _provider_data(volume_payload),
        "volume_daily_preview": daily_rows[:10],
        "quote_preview": quote_rows[:DEFAULT_QUOTE_CONTRACT_LIMIT],
        "risk_summary": _option_risk_summary(volume_payload, daily_rows, quote_rows),
    }


def _options_context_summary(symbol_data: dict[str, Any]) -> dict[str, Any]:
    high_put_call = 0
    for item in symbol_data.values():
        risk = item.get("risk_summary") if isinstance(item, dict) and isinstance(item.get("risk_summary"), dict) else {}
        if risk.get("put_call_signal") in {"put_pressure_high", "put_pressure_extreme"}:
            high_put_call += 1
    return {
        "symbol_count": len(symbol_data),
        "symbols_with_expirations": sum(1 for item in symbol_data.values() if isinstance(item, dict) and item.get("expirations")),
        "symbols_with_chain": sum(1 for item in symbol_data.values() if isinstance(item, dict) and item.get("chain_preview")),
        "symbols_with_volume": sum(1 for item in symbol_data.values() if isinstance(item, dict) and item.get("volume_snapshot")),
        "symbols_with_quotes": sum(1 for item in symbol_data.values() if isinstance(item, dict) and item.get("quote_preview")),
        "high_put_call_count": high_put_call,
    }


def _option_risk_summary(volume_payload: dict[str, Any], daily_rows: list[dict[str, Any]], quote_rows: list[dict[str, Any]]) -> dict[str, Any]:
    volume_data = _provider_data(volume_payload)
    latest_pc_vol = _to_float(
        _pick_from_any(volume_data, ("pc_ratio", "pc_vol", "put_call_ratio", "put_call_volume_ratio"))
    )
    if not latest_pc_vol and daily_rows:
        latest_pc_vol = _to_float(daily_rows[0].get("pc_vol"))
    latest_pc_oi = _to_float(_pick_from_any(volume_data, ("pc_oi", "put_call_open_interest_ratio")))
    if not latest_pc_oi and daily_rows:
        latest_pc_oi = _to_float(daily_rows[0].get("pc_oi"))
    signal = "unknown"
    if latest_pc_vol >= 1.5:
        signal = "put_pressure_extreme"
    elif latest_pc_vol >= 1.0:
        signal = "put_pressure_high"
    elif latest_pc_vol and latest_pc_vol <= 0.5:
        signal = "call_skew_high"
    elif latest_pc_vol:
        signal = "balanced"
    avg_iv = _average([_to_float(row.get("implied_volatility")) for row in quote_rows])
    return {
        "latest_pc_vol": latest_pc_vol,
        "latest_pc_oi": latest_pc_oi,
        "put_call_signal": signal,
        "avg_implied_volatility": avg_iv,
        "quote_count": len(quote_rows),
    }


def _extract_expirations(payload: Any) -> list[str]:
    rows = _extract_rows(payload)
    result: list[str] = []
    for row in rows:
        if isinstance(row, str):
            value = row.strip()
        elif isinstance(row, dict):
            value = str(row.get("expiry_date") or row.get("expiration_date") or row.get("date") or "").strip()
        else:
            value = ""
        if value:
            result.append(value[:10])
    if not result and isinstance(payload, dict):
        body = payload.get("data", payload)
        if isinstance(body, dict):
            for key in ("expirations", "expiry_dates", "dates"):
                values = body.get(key)
                if isinstance(values, list):
                    result.extend(str(value).strip()[:10] for value in values if str(value).strip())
    return sorted(_dedupe(result))


def _nearest_expirations(provider_payload: dict[str, Any], *, limit: int) -> list[str]:
    data = provider_payload.get("data") if isinstance(provider_payload.get("data"), dict) else {}
    expirations = data.get("expirations") if isinstance(data.get("expirations"), list) else []
    return [str(item) for item in expirations[:limit]]


def _nearest_expiration_from_provider_payload(provider_payload: dict[str, Any]) -> str:
    expirations = _nearest_expirations(provider_payload, limit=1)
    return expirations[0] if expirations else ""


def _compact_chain_rows(payload: Any, *, limit: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in _extract_rows(payload)[:limit]:
        if not isinstance(row, dict):
            continue
        result.append(
            {
                "strike": _pick_from_any(row, ("strike", "strike_price")),
                "standard": str(row.get("standard") or ""),
                "call_symbol": str(row.get("call_symbol") or ""),
                "put_symbol": str(row.get("put_symbol") or ""),
            }
        )
    return result


def _compact_quote_rows(payload: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in _extract_rows(payload):
        if not isinstance(row, dict):
            continue
        result.append(
            {
                "symbol": str(row.get("symbol") or ""),
                "last": _to_float(row.get("last") or row.get("last_done")),
                "bid": _to_float(row.get("bid") or row.get("bid_price")),
                "ask": _to_float(row.get("ask") or row.get("ask_price")),
                "open_interest": _to_float(row.get("open_interest")),
                "implied_volatility": _to_float(row.get("implied_volatility") or row.get("iv")),
                "delta": _to_float(row.get("delta")),
                "gamma": _to_float(row.get("gamma")),
                "theta": _to_float(row.get("theta")),
                "vega": _to_float(row.get("vega")),
            }
        )
    return result


def _compact_volume_daily_rows(payload: Any, *, limit: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in _extract_rows(payload)[:limit]:
        if not isinstance(row, dict):
            continue
        result.append(
            {
                "date": str(row.get("date") or row.get("time") or ""),
                "total_vol": _to_float(row.get("total_vol") or row.get("total_volume")),
                "call_vol": _to_float(row.get("call_vol") or row.get("call_volume")),
                "put_vol": _to_float(row.get("put_vol") or row.get("put_volume")),
                "pc_vol": _to_float(row.get("pc_vol") or row.get("pc_ratio")),
                "call_oi": _to_float(row.get("call_oi") or row.get("call_open_interest")),
                "put_oi": _to_float(row.get("put_oi") or row.get("put_open_interest")),
                "pc_oi": _to_float(row.get("pc_oi")),
            }
        )
    return result


def _option_volume_summary(payload: Any, symbol: str) -> dict[str, Any]:
    body = _payload_body(payload)
    return {
        "symbol": symbol,
        "call_vol": _to_float(_pick_from_any(body, ("call_vol", "call_volume"))),
        "put_vol": _to_float(_pick_from_any(body, ("put_vol", "put_volume"))),
        "pc_ratio": _to_float(_pick_from_any(body, ("pc_ratio", "pc_vol", "put_call_ratio"))),
    }


def _contract_symbols_from_chain(chain_payload: dict[str, Any]) -> list[str]:
    rows = _provider_data_rows(chain_payload, key="rows")
    contracts: list[str] = []
    for row in rows:
        for key in ("call_symbol", "put_symbol"):
            value = str(row.get(key) or "").strip().upper()
            if value:
                contracts.append(value)
    return _dedupe(contracts)


def _provider_data(payload: dict[str, Any]) -> Any:
    if not isinstance(payload, dict) or payload.get("status") == "error":
        return {}
    return payload.get("data") if "data" in payload else {}


def _provider_data_rows(payload: dict[str, Any], *, key: str) -> list[dict[str, Any]]:
    data = _provider_data(payload)
    if isinstance(data, dict) and isinstance(data.get(key), list):
        return [row for row in data[key] if isinstance(row, dict)]
    return []


def _summary_number(payload: dict[str, Any], key: str) -> int:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    return int(_to_float(summary.get(key)))


def _count_rows(payload: Any) -> int:
    return len(_extract_rows(payload))


def _extract_rows(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    body = payload.get("data", payload)
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("list", "items", "rows", "chain", "quotes", "expirations"):
            value = body.get(key)
            if isinstance(value, list):
                return value
        nested = body.get("data")
        if nested is not body:
            return _extract_rows(nested)
    return []


def _payload_body(payload: Any) -> Any:
    if isinstance(payload, dict):
        return payload.get("data", payload)
    return payload


def _pick_from_any(payload: Any, keys: tuple[str, ...]) -> Any:
    body = _payload_body(payload)
    if not isinstance(body, dict):
        return ""
    for key in keys:
        value = body.get(key)
        if value not in (None, ""):
            return value
    return ""


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


def _clean_contract_symbols(symbols: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for symbol in symbols:
        clean = str(symbol or "").strip().upper()
        if not clean:
            continue
        if "." not in clean:
            clean += ".US"
        if clean not in seen:
            result.append(clean)
            seen.add(clean)
    return result


def _clean_market(value: str | None) -> str:
    clean = str(value or "US").strip().upper()
    if clean in {"A", "ASHARE", "A_SHARE"}:
        clean = "CN"
    if clean not in VALID_MARKETS:
        raise ValueError(f"不支持的市场：{value}")
    return clean


def _clean_date(value: date | str) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return date.fromisoformat(str(value)).isoformat()


def _to_float(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _average(values: list[float]) -> float:
    usable = [value for value in values if value]
    if not usable:
        return 0.0
    return round(sum(usable) / len(usable), 6)


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()
