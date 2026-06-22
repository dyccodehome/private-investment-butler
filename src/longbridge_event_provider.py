"""Longbridge read-only news, filing and topic event provider."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from typing import Any, Sequence

from src.longbridge_capabilities import assert_longbridge_command_allowed, assert_read_capability
from src.longbridge_fundamental_provider import fetch_finance_calendar
from src.longbridge_provider import longbridge_env


READ_ONLY_WRITE_POLICY = "read_only_event_data; no posting, subscription changes, order placement, amendment, or cancellation"
DEFAULT_SYMBOL_LIMIT = 6
DEFAULT_ITEM_LIMIT = 5
MAX_ITEM_LIMIT = 20
VALID_MARKETS = {"US", "HK", "CN", "SG", "SH", "SZ"}


def fetch_symbol_news(symbol: str, *, count: int = DEFAULT_ITEM_LIMIT, timeout_seconds: int = 15) -> dict[str, Any]:
    clean_symbol = _clean_symbol(symbol)
    clean_count = _clean_count(count)
    command = ["longbridge", "news", clean_symbol, "--count", str(clean_count), "--format", "json"]
    payload = _run_json_command("news", command, timeout_seconds=timeout_seconds)
    return _provider_payload(
        scope="symbol_news",
        command=command,
        data=payload,
        summary=_row_count_summary(payload, symbol=clean_symbol, key="news_count"),
    )


def search_news(query: str, *, count: int = DEFAULT_ITEM_LIMIT, timeout_seconds: int = 15) -> dict[str, Any]:
    clean_query = _clean_query(query)
    clean_count = _clean_count(count)
    command = ["longbridge", "news", "search", clean_query, "--count", str(clean_count), "--format", "json"]
    payload = _run_json_command("news", command, timeout_seconds=timeout_seconds)
    return _provider_payload(
        scope="news_search",
        command=command,
        data=payload,
        summary=_row_count_summary(payload, key="news_count"),
    )


def fetch_symbol_filings(symbol: str, *, timeout_seconds: int = 15) -> dict[str, Any]:
    clean_symbol = _clean_symbol(symbol)
    command = ["longbridge", "filing", clean_symbol, "--format", "json"]
    payload = _run_json_command("filing", command, timeout_seconds=timeout_seconds)
    return _provider_payload(
        scope="symbol_filings",
        command=command,
        data=payload,
        summary=_row_count_summary(payload, symbol=clean_symbol, key="filing_count"),
    )


def fetch_symbol_topics(symbol: str, *, timeout_seconds: int = 15) -> dict[str, Any]:
    clean_symbol = _clean_symbol(symbol)
    command = ["longbridge", "topic", clean_symbol, "--format", "json"]
    payload = _run_json_command("topic", command, timeout_seconds=timeout_seconds)
    return _provider_payload(
        scope="symbol_topics",
        command=command,
        data=payload,
        summary=_row_count_summary(payload, symbol=clean_symbol, key="topic_count"),
    )


def search_topics(query: str, *, count: int = DEFAULT_ITEM_LIMIT, timeout_seconds: int = 15) -> dict[str, Any]:
    clean_query = _clean_query(query)
    clean_count = _clean_count(count)
    command = ["longbridge", "topic", "search", clean_query, "--count", str(clean_count), "--format", "json"]
    payload = _run_json_command("topic", command, timeout_seconds=timeout_seconds)
    return _provider_payload(
        scope="topic_search",
        command=command,
        data=payload,
        summary=_row_count_summary(payload, key="topic_count"),
    )


def build_event_context_snapshot(
    *,
    symbols: list[str],
    market: str = "US",
    symbol_limit: int = DEFAULT_SYMBOL_LIMIT,
    item_limit: int = DEFAULT_ITEM_LIMIT,
    include_filings: bool = True,
    include_topics: bool = True,
    include_calendar: bool = True,
    timeout_seconds: int = 15,
) -> dict[str, Any]:
    """Build a partial-tolerant event snapshot for scheduled reviews."""

    clean_market = _clean_market(market)
    clean_symbols = _clean_symbols(symbols)[: max(1, symbol_limit)]
    clean_item_limit = _clean_count(item_limit)
    sections: dict[str, Any] = {}
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

        collect("news", lambda symbol=symbol: fetch_symbol_news(symbol, count=clean_item_limit, timeout_seconds=timeout_seconds))
        if include_filings:
            collect("filings", lambda symbol=symbol: fetch_symbol_filings(symbol, timeout_seconds=timeout_seconds))
        if include_topics:
            collect("topics", lambda symbol=symbol: fetch_symbol_topics(symbol, timeout_seconds=timeout_seconds))
        sections[symbol] = symbol_sections

    calendar_sections: dict[str, Any] = {}
    if include_calendar:
        for calendar_type in ("report", "dividend"):
            try:
                payload = fetch_finance_calendar(calendar_type, market=clean_market, timeout_seconds=timeout_seconds)
            except RuntimeError as exc:
                source_chain.append(
                    {
                        "provider": "longbridge_cli",
                        "scope": f"finance_calendar:{calendar_type}",
                        "status": "error",
                        "error": str(exc),
                    }
                )
                calendar_sections[calendar_type] = {"status": "error", "error": str(exc), "data": None}
                continue
            source_chain.append(
                {
                    "provider": "longbridge_cli",
                    "scope": f"finance_calendar:{calendar_type}",
                    "status": "ok",
                    "error": "",
                }
            )
            calendar_sections[calendar_type] = payload

    warnings = [str(item.get("error")) for item in source_chain if item.get("status") != "ok" and item.get("error")]
    status = "ok" if not warnings else "partial"
    symbol_data = {
        symbol: _compact_symbol_events(sections.get(symbol) or {}, item_limit=clean_item_limit)
        for symbol in clean_symbols
    }
    return {
        "source": "longbridge_cli",
        "scope": "event_context_snapshot",
        "as_of": _now_iso(),
        "market": clean_market,
        "symbols": clean_symbols,
        "sections": sections,
        "calendar": calendar_sections,
        "symbol_data": symbol_data,
        "summary": _event_context_summary(symbol_data, calendar_sections),
        "data_quality": {
            "status": status,
            "source_chain": source_chain,
            "limitations": warnings,
            "symbol_limit": symbol_limit,
            "item_limit": clean_item_limit,
        },
        "write_policy": READ_ONLY_WRITE_POLICY,
    }


def format_event_context_snapshot(snapshot: dict[str, Any]) -> str:
    summary = snapshot.get("summary") or {}
    quality = snapshot.get("data_quality") or {}
    lines = [
        "长桥资讯事件只读快照",
        f"- 市场：{snapshot.get('market')}",
        f"- 状态：{quality.get('status') or 'unknown'}",
        f"- 覆盖标的：{summary.get('symbol_count', 0)}",
        f"- 资讯：{summary.get('news_count', 0)}",
        f"- 披露/filing：{summary.get('filing_count', 0)}",
        f"- 社区话题：{summary.get('topic_count', 0)}",
        f"- 财经日历事件：{summary.get('calendar_event_count', 0)}",
        f"- 写入策略：{snapshot.get('write_policy')}",
    ]
    symbol_data = snapshot.get("symbol_data") if isinstance(snapshot.get("symbol_data"), dict) else {}
    if symbol_data:
        lines.extend(["", "标的摘要："])
        for symbol, item in list(symbol_data.items())[:10]:
            if not isinstance(item, dict):
                continue
            title = _first_title(item.get("news") or item.get("filings") or item.get("topics") or [])
            lines.append(
                f"- {symbol}：news={len(item.get('news') or [])}，"
                f"filings={len(item.get('filings') or [])}，topics={len(item.get('topics') or [])}，"
                f"latest={title or 'NA'}"
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


def _compact_symbol_events(sections: dict[str, Any], *, item_limit: int) -> dict[str, Any]:
    news = _section_data(sections, "news")
    filings = _section_data(sections, "filings")
    topics = _section_data(sections, "topics")
    return {
        "news": _compact_event_items(news, limit=item_limit),
        "filings": _compact_event_items(filings, limit=item_limit),
        "topics": _compact_event_items(topics, limit=item_limit),
    }


def _event_context_summary(symbol_data: dict[str, Any], calendar_sections: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol_count": len(symbol_data),
        "news_count": sum(len(item.get("news") or []) for item in symbol_data.values() if isinstance(item, dict)),
        "filing_count": sum(len(item.get("filings") or []) for item in symbol_data.values() if isinstance(item, dict)),
        "topic_count": sum(len(item.get("topics") or []) for item in symbol_data.values() if isinstance(item, dict)),
        "calendar_event_count": sum(_count_rows(_section_data(calendar_sections, key)) for key in calendar_sections),
    }


def _compact_event_items(payload: Any, *, limit: int) -> list[dict[str, Any]]:
    rows = _extract_rows(payload)
    result: list[dict[str, Any]] = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        result.append(
            {
                "id": _pick_first_text(row, ("id", "article_id", "topic_id", "filing_id")),
                "title": _pick_first_text(row, ("title", "name", "file_name", "form_type")),
                "summary": _pick_first_text(row, ("summary", "description", "text", "content", "abstract")),
                "published_at": _pick_first_text(row, ("published_at", "publish_at", "created_at", "date", "time")),
                "url": _pick_first_text(row, ("url", "link", "source_url")),
                "source": _pick_first_text(row, ("source", "publisher", "author")),
                "likes": _pick_first_text(row, ("likes", "likes_count")),
                "comments": _pick_first_text(row, ("comments", "comments_count")),
                "file_urls": row.get("file_urls") if isinstance(row.get("file_urls"), list) else [],
            }
        )
    return result


def _section_data(sections: dict[str, Any], key: str) -> Any:
    section = sections.get(key) if isinstance(sections.get(key), dict) else {}
    if section.get("status") == "error":
        return {}
    return section.get("data") if "data" in section else {}


def _row_count_summary(payload: Any, *, symbol: str = "", key: str = "row_count") -> dict[str, Any]:
    summary = {key: _count_rows(payload)}
    if symbol:
        summary["symbol"] = symbol
    return summary


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
        for key in ("list", "items", "rows", "news", "filings", "topics", "events"):
            value = body.get(key)
            if isinstance(value, list):
                return value
        nested = body.get("data")
        if nested is not body:
            return _extract_rows(nested)
    return []


def _pick_first_text(payload: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _first_title(items: list[dict[str, Any]]) -> str:
    for item in items:
        title = str(item.get("title") or "").strip()
        if title:
            return title[:80]
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


def _clean_query(query: str) -> str:
    clean = str(query or "").strip()
    if not clean:
        raise ValueError("query 不能为空。")
    return clean


def _clean_count(count: int) -> int:
    return max(1, min(MAX_ITEM_LIMIT, int(count or DEFAULT_ITEM_LIMIT)))


def _clean_market(value: str | None) -> str:
    clean = str(value or "US").strip().upper()
    if clean in {"A", "ASHARE", "A_SHARE"}:
        clean = "CN"
    if clean not in VALID_MARKETS:
        raise ValueError(f"不支持的市场：{value}")
    return clean


def _now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()
