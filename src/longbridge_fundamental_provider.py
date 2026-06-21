"""Longbridge read-only fundamental data provider."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from typing import Any, Sequence

from src.longbridge_capabilities import assert_longbridge_command_allowed, assert_read_capability
from src.longbridge_provider import longbridge_env


READ_ONLY_WRITE_POLICY = "read_only_fundamental_data; no order placement, amendment, or cancellation"
DEFAULT_SYMBOL_LIMIT = 6
DEFAULT_PREVIEW_LIMIT = 8
VALID_REPORT_KINDS = {"ALL", "IS", "BS", "CF"}
VALID_REPORT_PERIODS = {"af", "saf", "q1", "3q", "qf", "cumul"}
VALID_VALUATION_INDICATORS = {"pe", "pb", "ps", "dvd_yld"}
VALID_CALENDAR_TYPES = {"report", "dividend", "split", "ipo", "macrodata", "closed"}
VALID_CALENDAR_FILTERS = {"watchlist", "positions"}
VALID_MARKETS = {"US", "HK", "CN", "SG", "SH", "SZ"}


def fetch_company_profile(symbol: str, *, timeout_seconds: int = 15) -> dict[str, Any]:
    clean_symbol = _clean_symbol(symbol)
    command = ["longbridge", "company", clean_symbol, "--format", "json"]
    payload = _run_json_command("company_profile", command, timeout_seconds=timeout_seconds)
    return _provider_payload(
        scope="company_profile",
        command=command,
        data=payload,
        summary=_company_summary(payload, clean_symbol),
    )


def fetch_valuation(
    symbol: str,
    *,
    indicator: str | None = None,
    history: bool = False,
    range_years: int | None = None,
    timeout_seconds: int = 15,
) -> dict[str, Any]:
    clean_symbol = _clean_symbol(symbol)
    command = ["longbridge", "valuation", clean_symbol]
    clean_indicator = _clean_valuation_indicator(indicator)
    if history:
        command.append("--history")
    if clean_indicator:
        command.extend(["--indicator", clean_indicator])
    if range_years:
        command.extend(["--range", str(_clean_range_years(range_years))])
    command.extend(["--format", "json"])
    payload = _run_json_command("valuation", command, timeout_seconds=timeout_seconds)
    return _provider_payload(
        scope="valuation",
        command=command,
        data=payload,
        summary=_valuation_summary(payload, clean_symbol),
    )


def fetch_financial_report(
    symbol: str,
    *,
    kind: str = "ALL",
    report: str | None = None,
    timeout_seconds: int = 15,
) -> dict[str, Any]:
    clean_symbol = _clean_symbol(symbol)
    command = ["longbridge", "financial-report", clean_symbol]
    clean_kind = _clean_report_kind(kind)
    if clean_kind != "ALL":
        command.extend(["--kind", clean_kind])
    clean_report = _clean_report_period(report)
    if clean_report:
        command.extend(["--report", clean_report])
    command.extend(["--format", "json"])
    payload = _run_json_command("financial_report", command, timeout_seconds=timeout_seconds)
    return _provider_payload(
        scope="financial_report",
        command=command,
        data=payload,
        summary=_row_count_summary(payload, symbol=clean_symbol),
    )


def fetch_financial_report_snapshot(
    symbol: str,
    *,
    report: str | None = None,
    year: int | None = None,
    period: int | None = None,
    timeout_seconds: int = 15,
) -> dict[str, Any]:
    clean_symbol = _clean_symbol(symbol)
    command = ["longbridge", "financial-report", "snapshot", clean_symbol]
    clean_report = _clean_report_period(report)
    if clean_report:
        command.extend(["--report", clean_report])
    if year:
        command.extend(["--year", str(int(year))])
    if period:
        command.extend(["--period", str(int(period))])
    command.extend(["--format", "json"])
    payload = _run_json_command("financial_report", command, timeout_seconds=timeout_seconds)
    return _provider_payload(
        scope="financial_report_snapshot",
        command=command,
        data=payload,
        summary=_financial_snapshot_summary(payload, clean_symbol),
    )


def fetch_financial_statement(
    symbol: str,
    *,
    kind: str = "ALL",
    report: str | None = None,
    timeout_seconds: int = 15,
) -> dict[str, Any]:
    clean_symbol = _clean_symbol(symbol)
    command = ["longbridge", "financial-statement", clean_symbol]
    clean_kind = _clean_report_kind(kind)
    if clean_kind != "ALL":
        command.extend(["--kind", clean_kind])
    clean_report = _clean_report_period(report)
    if clean_report:
        command.extend(["--report", clean_report])
    command.extend(["--format", "json"])
    payload = _run_json_command("financial_statement", command, timeout_seconds=timeout_seconds)
    return _provider_payload(
        scope="financial_statement",
        command=command,
        data=payload,
        summary=_row_count_summary(payload, symbol=clean_symbol),
    )


def fetch_forecast_eps(symbol: str, *, timeout_seconds: int = 15) -> dict[str, Any]:
    clean_symbol = _clean_symbol(symbol)
    command = ["longbridge", "forecast-eps", clean_symbol, "--format", "json"]
    payload = _run_json_command("forecast_eps", command, timeout_seconds=timeout_seconds)
    return _provider_payload(
        scope="forecast_eps",
        command=command,
        data=payload,
        summary=_forecast_eps_summary(payload, clean_symbol),
    )


def fetch_consensus(symbol: str, *, timeout_seconds: int = 15) -> dict[str, Any]:
    clean_symbol = _clean_symbol(symbol)
    command = ["longbridge", "consensus", clean_symbol, "--format", "json"]
    payload = _run_json_command("consensus", command, timeout_seconds=timeout_seconds)
    return _provider_payload(
        scope="consensus",
        command=command,
        data=payload,
        summary=_consensus_summary(payload, clean_symbol),
    )


def fetch_dividend_history(symbol: str, *, detail: bool = False, timeout_seconds: int = 15) -> dict[str, Any]:
    clean_symbol = _clean_symbol(symbol)
    command = ["longbridge", "dividend"]
    if detail:
        command.append("detail")
    command.extend([clean_symbol, "--format", "json"])
    payload = _run_json_command("dividend", command, timeout_seconds=timeout_seconds)
    return _provider_payload(
        scope="dividend_history_detail" if detail else "dividend_history",
        command=command,
        data=payload,
        summary=_row_count_summary(payload, symbol=clean_symbol, key="dividend_count"),
    )


def fetch_finance_calendar(
    calendar_type: str,
    *,
    market: str | None = None,
    filter_type: str | None = None,
    star: int | None = None,
    timeout_seconds: int = 15,
) -> dict[str, Any]:
    clean_type = _clean_calendar_type(calendar_type)
    command = ["longbridge", "finance-calendar", clean_type]
    clean_filter = _clean_calendar_filter(filter_type)
    clean_market = _clean_market(market) if market else ""
    if clean_filter:
        command.extend(["--filter", clean_filter])
    if clean_market:
        command.extend(["--market", clean_market])
    if star is not None:
        command.extend(["--star", str(int(star))])
    command.extend(["--format", "json"])
    payload = _run_json_command("finance_calendar", command, timeout_seconds=timeout_seconds)
    return _provider_payload(
        scope=f"finance_calendar_{clean_type}",
        command=command,
        data=payload,
        summary=_row_count_summary(payload, key="event_count"),
    )


def build_fundamental_context_snapshot(
    *,
    symbols: list[str],
    market: str = "US",
    symbol_limit: int = DEFAULT_SYMBOL_LIMIT,
    include_dividends: bool = True,
    include_financial_report_snapshot: bool = True,
    timeout_seconds: int = 15,
) -> dict[str, Any]:
    """Build a partial-tolerant fundamental snapshot for scheduled reviews."""

    clean_market = _clean_market(market)
    clean_symbols = _clean_symbols(symbols)[: max(1, symbol_limit)]
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

        collect("company_profile", lambda symbol=symbol: fetch_company_profile(symbol, timeout_seconds=timeout_seconds))
        collect("valuation", lambda symbol=symbol: fetch_valuation(symbol, timeout_seconds=timeout_seconds))
        if include_financial_report_snapshot:
            collect(
                "financial_report_snapshot",
                lambda symbol=symbol: fetch_financial_report_snapshot(symbol, timeout_seconds=timeout_seconds),
            )
        collect("forecast_eps", lambda symbol=symbol: fetch_forecast_eps(symbol, timeout_seconds=timeout_seconds))
        collect("consensus", lambda symbol=symbol: fetch_consensus(symbol, timeout_seconds=timeout_seconds))
        if include_dividends:
            collect("dividend_history", lambda symbol=symbol: fetch_dividend_history(symbol, timeout_seconds=timeout_seconds))
        sections[symbol] = symbol_sections

    warnings = [str(item.get("error")) for item in source_chain if item.get("status") != "ok" and item.get("error")]
    status = "ok" if not warnings else "partial"
    symbol_data = {symbol: _compact_symbol_fundamentals(sections.get(symbol) or {}) for symbol in clean_symbols}
    return {
        "source": "longbridge_cli",
        "scope": "fundamental_context_snapshot",
        "as_of": _now_iso(),
        "market": clean_market,
        "symbols": clean_symbols,
        "sections": sections,
        "symbol_data": symbol_data,
        "summary": _fundamental_context_summary(symbol_data),
        "data_quality": {
            "status": status,
            "source_chain": source_chain,
            "limitations": warnings,
            "symbol_limit": symbol_limit,
        },
        "write_policy": READ_ONLY_WRITE_POLICY,
    }


def format_fundamental_context_snapshot(snapshot: dict[str, Any]) -> str:
    summary = snapshot.get("summary") or {}
    quality = snapshot.get("data_quality") or {}
    lines = [
        "长桥基本面只读快照",
        f"- 市场：{snapshot.get('market')}",
        f"- 状态：{quality.get('status') or 'unknown'}",
        f"- 覆盖标的：{summary.get('symbol_count', 0)}",
        f"- 公司概况：{summary.get('company_profile_count', 0)}",
        f"- 估值：{summary.get('valuation_count', 0)}",
        f"- 财报速览：{summary.get('financial_report_snapshot_count', 0)}",
        f"- EPS 预测：{summary.get('forecast_eps_count', 0)}",
        f"- 一致预期：{summary.get('consensus_count', 0)}",
        f"- 分红历史：{summary.get('dividend_history_count', 0)}",
        f"- 写入策略：{snapshot.get('write_policy')}",
    ]
    symbol_data = snapshot.get("symbol_data") if isinstance(snapshot.get("symbol_data"), dict) else {}
    if symbol_data:
        lines.extend(["", "标的摘要："])
        for symbol, item in list(symbol_data.items())[:10]:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- {symbol}：company={item.get('company_name') or 'NA'}，"
                f"valuation={item.get('valuation_desc') or 'NA'}，"
                f"dividends={item.get('dividend_count', 0)}"
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


def _compact_symbol_fundamentals(sections: dict[str, Any]) -> dict[str, Any]:
    company = _section_data(sections, "company_profile")
    valuation = _section_data(sections, "valuation")
    report = _section_data(sections, "financial_report_snapshot")
    forecast = _section_data(sections, "forecast_eps")
    consensus = _section_data(sections, "consensus")
    dividend = _section_data(sections, "dividend_history")
    return {
        "company_name": _pick_first_text(company, ("name", "company_name", "symbol_name", "short_name")),
        "industry": _pick_first_text(company, ("industry", "sector", "market", "exchange")),
        "website": _pick_first_text(company, ("website", "web_site")),
        "valuation_desc": _valuation_desc(valuation),
        "valuation_metrics": _compact_preview(valuation, limit=DEFAULT_PREVIEW_LIMIT),
        "financial_report_snapshot": _compact_preview(report, limit=DEFAULT_PREVIEW_LIMIT),
        "forecast_eps": _compact_preview(forecast, limit=DEFAULT_PREVIEW_LIMIT),
        "consensus": _compact_preview(consensus, limit=DEFAULT_PREVIEW_LIMIT),
        "dividend_count": _count_rows(dividend),
        "dividend_preview": _compact_preview(dividend, limit=5),
    }


def _fundamental_context_summary(symbol_data: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol_count": len(symbol_data),
        "company_profile_count": sum(1 for item in symbol_data.values() if item.get("company_name") or item.get("industry")),
        "valuation_count": sum(1 for item in symbol_data.values() if item.get("valuation_desc") or item.get("valuation_metrics")),
        "financial_report_snapshot_count": sum(1 for item in symbol_data.values() if item.get("financial_report_snapshot")),
        "forecast_eps_count": sum(1 for item in symbol_data.values() if item.get("forecast_eps")),
        "consensus_count": sum(1 for item in symbol_data.values() if item.get("consensus")),
        "dividend_history_count": sum(1 for item in symbol_data.values() if item.get("dividend_count")),
    }


def _section_data(sections: dict[str, Any], key: str) -> Any:
    section = sections.get(key) if isinstance(sections.get(key), dict) else {}
    if section.get("status") == "error":
        return {}
    return section.get("data") if "data" in section else {}


def _company_summary(payload: Any, symbol: str) -> dict[str, Any]:
    body = _payload_body(payload)
    return {
        "symbol": symbol,
        "company_name": _pick_first_text(body, ("name", "company_name", "symbol_name", "short_name")),
        "industry": _pick_first_text(body, ("industry", "sector", "market", "exchange")),
    }


def _valuation_summary(payload: Any, symbol: str) -> dict[str, Any]:
    body = _payload_body(payload)
    return {
        "symbol": symbol,
        "desc": _valuation_desc(body),
        "metric_count": len(body.get("metrics") or {}) if isinstance(body, dict) else _count_rows(body),
    }


def _financial_snapshot_summary(payload: Any, symbol: str) -> dict[str, Any]:
    body = _payload_body(payload)
    return {
        "symbol": symbol,
        "currency": _pick_first_text(body, ("currency",)),
        "period": _pick_first_text(body, ("period", "quarter", "report_period")),
        "row_count": _count_rows(body),
    }


def _forecast_eps_summary(payload: Any, symbol: str) -> dict[str, Any]:
    return {"symbol": symbol, "forecast_count": _count_rows(payload)}


def _consensus_summary(payload: Any, symbol: str) -> dict[str, Any]:
    return {"symbol": symbol, "period_count": _count_rows(payload)}


def _row_count_summary(payload: Any, *, symbol: str = "", key: str = "row_count") -> dict[str, Any]:
    summary = {key: _count_rows(payload)}
    if symbol:
        summary["symbol"] = symbol
    return summary


def _valuation_desc(payload: Any) -> str:
    body = _payload_body(payload)
    if isinstance(body, dict):
        if isinstance(body.get("desc"), str):
            return body["desc"]
        metrics = body.get("metrics")
        if isinstance(metrics, dict):
            for metric in metrics.values():
                if isinstance(metric, dict) and isinstance(metric.get("desc"), str):
                    return metric["desc"]
        for value in body.values():
            if isinstance(value, dict) and isinstance(value.get("desc"), str):
                return value["desc"]
    return ""


def _payload_body(payload: Any) -> Any:
    if isinstance(payload, dict):
        data = payload.get("data")
        if data is not None:
            return data
    return payload


def _compact_preview(value: Any, *, depth: int = 3, limit: int = DEFAULT_PREVIEW_LIMIT) -> Any:
    if depth <= 0:
        return "<truncated>"
    if isinstance(value, list):
        return [_compact_preview(item, depth=depth - 1, limit=limit) for item in value[:limit]]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= limit:
                result["..."] = f"{len(value) - limit} keys omitted"
                break
            result[str(key)] = _compact_preview(item, depth=depth - 1, limit=limit)
        return result
    return value


def _count_rows(payload: Any) -> int:
    body = _payload_body(payload)
    if isinstance(body, list):
        return len(body)
    if isinstance(body, dict):
        for key in ("items", "list", "rows", "data", "events", "dividends"):
            value = body.get(key)
            if isinstance(value, list):
                return len(value)
        if isinstance(body.get("list"), dict):
            return len(body["list"])
        return len(body) if body else 0
    return 0


def _pick_first_text(payload: Any, keys: tuple[str, ...]) -> str:
    body = _payload_body(payload)
    if not isinstance(body, dict):
        return ""
    for key in keys:
        value = body.get(key)
        if value not in (None, ""):
            return str(value).strip()
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


def _clean_report_kind(kind: str | None) -> str:
    clean = str(kind or "ALL").strip().upper()
    if clean not in VALID_REPORT_KINDS:
        raise ValueError(f"不支持的财报类型：{kind}")
    return clean


def _clean_report_period(report: str | None) -> str:
    clean = str(report or "").strip().lower()
    if clean and clean not in VALID_REPORT_PERIODS:
        raise ValueError(f"不支持的报告期：{report}")
    return clean


def _clean_valuation_indicator(indicator: str | None) -> str:
    clean = str(indicator or "").strip().lower()
    if clean and clean not in VALID_VALUATION_INDICATORS:
        raise ValueError(f"不支持的估值指标：{indicator}")
    return clean


def _clean_range_years(value: int) -> int:
    clean = int(value)
    if clean not in {1, 3, 5, 10}:
        raise ValueError("估值历史 range 只支持 1、3、5、10 年。")
    return clean


def _clean_calendar_type(value: str) -> str:
    clean = str(value or "").strip().lower()
    if clean not in VALID_CALENDAR_TYPES:
        raise ValueError(f"不支持的财经日历类型：{value}")
    return clean


def _clean_calendar_filter(value: str | None) -> str:
    clean = str(value or "").strip().lower()
    if clean and clean not in VALID_CALENDAR_FILTERS:
        raise ValueError(f"不支持的财经日历过滤器：{value}")
    return clean


def _clean_market(value: str | None) -> str:
    clean = str(value or "US").strip().upper()
    if clean in {"A", "ASHARE", "A_SHARE"}:
        clean = "CN"
    if clean not in VALID_MARKETS:
        raise ValueError(f"不支持的市场：{value}")
    return clean


def _now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()
