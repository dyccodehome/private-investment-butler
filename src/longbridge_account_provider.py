"""Longbridge read-only account and execution query provider."""

from __future__ import annotations

import json
import subprocess
from datetime import date, datetime, timedelta
from typing import Any, Sequence

from src.longbridge_capabilities import assert_longbridge_command_allowed, assert_read_capability
from src.longbridge_provider import longbridge_env


READ_ONLY_WRITE_POLICY = "read_only_account_data; no order placement, amendment, or cancellation"


def fetch_account_assets(
    *,
    currency: str = "USD",
    timeout_seconds: int = 15,
) -> dict[str, Any]:
    """Fetch account assets, cash, buying power and margin summary."""

    clean_currency = _clean_currency(currency)
    command = ["longbridge", "assets", "--currency", clean_currency, "--format", "json"]
    payload = _run_json_command("assets", command, timeout_seconds=timeout_seconds)
    return _provider_payload(
        scope="account_assets",
        command=command,
        data=payload,
        summary={
            "currency": clean_currency,
            "cash_info_count": _count_nested_rows(payload, "cash_infos"),
        },
    )


def fetch_portfolio_overview(*, timeout_seconds: int = 15) -> dict[str, Any]:
    """Fetch portfolio overview, holdings, cash and P/L summary."""

    command = ["longbridge", "portfolio", "--format", "json"]
    payload = _run_json_command("portfolio", command, timeout_seconds=timeout_seconds)
    return _provider_payload(
        scope="portfolio_overview",
        command=command,
        data=payload,
        summary={
            "holding_count": _count_nested_rows(payload, "holdings"),
            "cash_count": _count_nested_rows(payload, "cash"),
        },
    )


def fetch_order_history(
    *,
    start: date | str | None = None,
    end: date | str | None = None,
    symbol: str | None = None,
    timeout_seconds: int = 15,
) -> dict[str, Any]:
    """Fetch historical order list. This never submits, amends, or cancels orders."""

    command = ["longbridge", "order", "--history"]
    _append_optional_date_filters(command, start=start, end=end)
    _append_optional_symbol(command, symbol)
    command.extend(["--format", "json"])
    payload = _run_json_command("order_history", command, timeout_seconds=timeout_seconds)
    return _provider_payload(
        scope="order_history",
        command=command,
        data=payload,
        summary={"order_count": _count_rows(payload)},
    )


def fetch_execution_history(
    *,
    start: date | str | None = None,
    end: date | str | None = None,
    symbol: str | None = None,
    timeout_seconds: int = 15,
) -> dict[str, Any]:
    """Fetch historical trade executions/fills."""

    command = ["longbridge", "order", "executions", "--history"]
    _append_optional_date_filters(command, start=start, end=end)
    _append_optional_symbol(command, symbol)
    command.extend(["--format", "json"])
    payload = _run_json_command("execution_history", command, timeout_seconds=timeout_seconds)
    return _provider_payload(
        scope="execution_history",
        command=command,
        data=payload,
        summary={"execution_count": _count_rows(payload)},
    )


def fetch_profit_analysis(
    *,
    start: date | str | None = None,
    end: date | str | None = None,
    timeout_seconds: int = 15,
) -> dict[str, Any]:
    """Fetch account P/L analysis."""

    command = ["longbridge", "profit-analysis"]
    _append_optional_date_filters(command, start=start, end=end)
    command.extend(["--format", "json"])
    payload = _run_json_command("profit_analysis", command, timeout_seconds=timeout_seconds)
    return _provider_payload(
        scope="profit_analysis",
        command=command,
        data=payload,
        summary={},
    )


def build_account_activity_snapshot(
    *,
    days: int = 30,
    start: date | str | None = None,
    end: date | str | None = None,
    symbol: str | None = None,
    currency: str = "USD",
    include_profit_analysis: bool = False,
    timeout_seconds: int = 15,
) -> dict[str, Any]:
    """Build a partial-tolerant account snapshot for reviews."""

    clean_start, clean_end = _resolve_date_range(days=days, start=start, end=end)
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

    collect(
        "account_assets",
        lambda: fetch_account_assets(currency=currency, timeout_seconds=timeout_seconds),
    )
    collect("portfolio_overview", lambda: fetch_portfolio_overview(timeout_seconds=timeout_seconds))
    collect(
        "order_history",
        lambda: fetch_order_history(
            start=clean_start,
            end=clean_end,
            symbol=symbol,
            timeout_seconds=timeout_seconds,
        ),
    )
    collect(
        "execution_history",
        lambda: fetch_execution_history(
            start=clean_start,
            end=clean_end,
            symbol=symbol,
            timeout_seconds=timeout_seconds,
        ),
    )
    if include_profit_analysis:
        collect(
            "profit_analysis",
            lambda: fetch_profit_analysis(
                start=clean_start,
                end=clean_end,
                timeout_seconds=timeout_seconds,
            ),
        )

    warnings = [str(item.get("error")) for item in source_chain if item.get("status") != "ok" and item.get("error")]
    status = "ok" if not warnings else "partial"
    return {
        "source": "longbridge_cli",
        "scope": "account_activity_snapshot",
        "as_of": _now_iso(),
        "status": status,
        "period": {"start": clean_start.isoformat(), "end": clean_end.isoformat(), "days": days},
        "symbol": _clean_symbol(symbol),
        "currency": _clean_currency(currency),
        "sections": sections,
        "summary": _snapshot_summary(sections),
        "data_quality": {
            "source_chain": source_chain,
            "freshness": "fresh" if status == "ok" else "partial",
            "limitations": warnings,
        },
        "write_policy": READ_ONLY_WRITE_POLICY,
    }


def format_account_activity_snapshot(snapshot: dict[str, Any]) -> str:
    """Format an account activity snapshot for CLI/Feishu."""

    summary = snapshot.get("summary") or {}
    period = snapshot.get("period") or {}
    lines = [
        "长桥账户/成交只读快照",
        f"- 状态：{snapshot.get('status')}",
        f"- 区间：{period.get('start')} 至 {period.get('end')}",
        f"- 币种：{snapshot.get('currency')}",
        f"- 标的过滤：{snapshot.get('symbol') or '无'}",
        f"- 持仓条目：{summary.get('holding_count', 0)}",
        f"- 历史订单：{summary.get('order_count', 0)}",
        f"- 历史成交：{summary.get('execution_count', 0)}",
        f"- 现金条目：{summary.get('cash_info_count', 0)}",
        f"- 写入策略：{snapshot.get('write_policy')}",
    ]
    limitations = list((snapshot.get("data_quality") or {}).get("limitations") or [])
    if limitations:
        lines.append("")
        lines.append("数据缺口：")
        lines.extend(f"- {item}" for item in limitations)
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
        "data": data,
        "summary": summary,
        "write_policy": READ_ONLY_WRITE_POLICY,
    }


def _resolve_date_range(
    *,
    days: int,
    start: date | str | None,
    end: date | str | None,
) -> tuple[date, date]:
    clean_end = _parse_date(end) or date.today()
    clean_start = _parse_date(start) or (clean_end - timedelta(days=max(1, int(days or 30))))
    return clean_start, clean_end


def _append_optional_date_filters(command: list[str], *, start: date | str | None, end: date | str | None) -> None:
    clean_start = _parse_date(start)
    clean_end = _parse_date(end)
    if clean_start:
        command.extend(["--start", clean_start.isoformat()])
    if clean_end:
        command.extend(["--end", clean_end.isoformat()])


def _append_optional_symbol(command: list[str], symbol: str | None) -> None:
    clean = _clean_symbol(symbol)
    if clean:
        command.extend(["--symbol", clean])


def _snapshot_summary(sections: dict[str, Any]) -> dict[str, Any]:
    assets = _section_summary(sections, "account_assets")
    portfolio = _section_summary(sections, "portfolio_overview")
    orders = _section_summary(sections, "order_history")
    executions = _section_summary(sections, "execution_history")
    return {
        "cash_info_count": assets.get("cash_info_count", 0),
        "holding_count": portfolio.get("holding_count", 0),
        "order_count": orders.get("order_count", 0),
        "execution_count": executions.get("execution_count", 0),
    }


def _section_summary(sections: dict[str, Any], key: str) -> dict[str, Any]:
    section = sections.get(key) if isinstance(sections.get(key), dict) else {}
    summary = section.get("summary") if isinstance(section.get("summary"), dict) else {}
    return summary


def _count_rows(payload: Any) -> int:
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        for key in ("orders", "executions", "list", "items", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return len(value)
        if isinstance(payload.get("data"), dict):
            return _count_rows(payload["data"])
    return 0


def _count_nested_rows(payload: Any, key: str) -> int:
    if isinstance(payload, dict):
        value = payload.get(key)
        if isinstance(value, list):
            return len(value)
        for nested_key in ("data", "overview", "portfolio"):
            nested = payload.get(nested_key)
            if isinstance(nested, dict):
                count = _count_nested_rows(nested, key)
                if count:
                    return count
    return 0


def _parse_date(value: date | str | None) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _clean_currency(value: str | None) -> str:
    clean = str(value or "USD").strip().upper()
    return clean or "USD"


def _clean_symbol(value: str | None) -> str:
    return str(value or "").strip().upper()


def _now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()
