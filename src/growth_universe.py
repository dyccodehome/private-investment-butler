"""Longbridge-backed Growth Engine investable universe.

Growth Engine no longer keeps a manual watchlist as its source of truth. The
daily and weekly workflows use this module to normalize Longbridge positions
and watchlists into one read-only US universe.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.app_config import get_config
from src.init import RUNTIME_DIR
from src.longbridge_provider import (
    CASH_ANCHOR_SYMBOLS,
    sync_longbridge_growth_positions,
    sync_longbridge_watchlist,
)


GROWTH_UNIVERSE_RULE = (
    "Growth Engine 美股 universe 完全来自长桥持仓和长桥自选；"
    "QQQI/XQQI/TQQQ 等 Cash Anchor 固定现金流标的排除；"
    "期权合约不入池，只映射到底层股票；2x/3x 杠杆 ETF 排除；普通 ETF 可以入池。"
)

DEFAULT_LEVERAGED_ETF_SYMBOLS = {
    "CONL",
    "FNGD",
    "FNGU",
    "LABD",
    "LABU",
    "MSTU",
    "MSTX",
    "MSTZ",
    "NVDL",
    "NVDQ",
    "NVDU",
    "SOXL",
    "SOXS",
    "SPXL",
    "SPXS",
    "SQQQ",
    "SVIX",
    "TECL",
    "TECS",
    "TQQQ",
    "TSLL",
    "TSLQ",
    "UPRO",
    "UVIX",
}

DEFAULT_SPECIAL_ETF_CLASSIFICATIONS = {
    "DRAM": {
        "asset_subtype": "memory_semiconductor_etf",
        "notes": "普通主题 ETF，聚焦存储与半导体周期，不属于杠杆 ETF。",
    },
    "SPCX": {
        "asset_subtype": "spac_new_issue_etf",
        "notes": "普通主题 ETF，聚焦 SPAC 与新上市公司，不属于杠杆 ETF。",
    },
}

DEFAULT_GROWTH_UNIVERSE_CACHE_TTL_SECONDS = 900


@dataclass(frozen=True)
class GrowthUniverseConfig:
    cache_enabled: bool = True
    cache_ttl_seconds: int = DEFAULT_GROWTH_UNIVERSE_CACHE_TTL_SECONDS
    leveraged_etf_blocklist: set[str] = field(default_factory=lambda: set(DEFAULT_LEVERAGED_ETF_SYMBOLS))
    leveraged_etf_allowlist: set[str] = field(default_factory=set)
    ordinary_etf_allowlist: set[str] = field(default_factory=lambda: set(DEFAULT_SPECIAL_ETF_CLASSIFICATIONS))
    special_etf_classifications: dict[str, dict[str, str]] = field(
        default_factory=lambda: dict(DEFAULT_SPECIAL_ETF_CLASSIFICATIONS)
    )


@dataclass
class GrowthUniverseItem:
    symbol: str
    name: str
    market: str = "US"
    asset_type: str = "stock"
    asset_subtype: str = "common_stock"
    classification_tags: list[str] = field(default_factory=list)
    source_types: list[str] = field(default_factory=list)
    source_symbols: list[str] = field(default_factory=list)
    source_groups: list[str] = field(default_factory=list)
    is_pinned: bool = False
    has_position: bool = False
    quantity: float | None = None
    available_quantity: float | None = None
    cost_price: float | None = None
    current_price: float | None = None
    currency: str = "USD"
    reason: str = ""


def sync_growth_universe(
    timeout_seconds: int = 15,
    *,
    use_cache: bool = True,
    refresh: bool = False,
) -> dict[str, Any]:
    """Read Longbridge and return the normalized Growth Engine universe."""

    config = load_growth_universe_config()
    if use_cache and not refresh and config.cache_enabled:
        cached = _read_cached_growth_universe(config)
        if cached:
            return cached

    positions = sync_longbridge_growth_positions(timeout_seconds=timeout_seconds)
    watchlist = sync_longbridge_watchlist(timeout_seconds=timeout_seconds)
    payload = build_growth_universe_payload(positions, watchlist, config=config)
    payload["cache"] = {
        "hit": False,
        "enabled": config.cache_enabled,
        "ttl_seconds": config.cache_ttl_seconds,
        "path": str(_cache_path()),
        "written_at": _now_iso(),
    }
    if config.cache_enabled:
        _write_cached_growth_universe(payload)
    return payload


def build_growth_universe_payload(
    position_payload: dict[str, Any],
    watchlist_payload: dict[str, Any],
    *,
    config: GrowthUniverseConfig | None = None,
) -> dict[str, Any]:
    """Build a single universe from Longbridge position and watchlist payloads."""

    active_config = config or load_growth_universe_config()
    universe: dict[str, GrowthUniverseItem] = {}
    excluded: list[dict[str, Any]] = []
    counters = {
        "source_positions": 0,
        "source_watch_items": 0,
        "option_contracts_mapped": 0,
        "option_underlyings_added": 0,
        "excluded_cash_anchor": 0,
        "excluded_leveraged_etf": 0,
        "excluded_index": 0,
        "excluded_non_us": 0,
        "stock_count": 0,
        "ordinary_etf_count": 0,
        "special_etf_count": 0,
        "option_underlying_stock_count": 0,
    }

    for row in _position_rows(position_payload):
        counters["source_positions"] += 1
        _process_source_row(row, "longbridge_position", universe, excluded, counters, active_config)

    for row in _watchlist_rows(watchlist_payload):
        counters["source_watch_items"] += 1
        _process_source_row(row, "longbridge_watchlist", universe, excluded, counters, active_config)

    items = sorted(
        (asdict(item) for item in universe.values()),
        key=lambda item: (not item.get("has_position"), not item.get("is_pinned"), item.get("symbol") or ""),
    )
    for item in items:
        if item["asset_type"] == "etf":
            counters["ordinary_etf_count"] += 1
            if item.get("asset_subtype") not in {"ordinary_etf", ""}:
                counters["special_etf_count"] += 1
        elif item["asset_type"] == "stock":
            counters["stock_count"] += 1
            if "option_underlying" in item.get("classification_tags", []):
                counters["option_underlying_stock_count"] += 1

    summary = {
        **counters,
        "universe_count": len(items),
        "excluded_count": len(excluded),
        "ignored_non_us_watch_items": (watchlist_payload.get("summary") or {}).get("ignored_non_us_watch_items", 0),
        "ignored_non_us_positions": (position_payload.get("summary") or {}).get("ignored_non_us_positions", 0),
    }
    summary["excluded_non_us"] += int(summary["ignored_non_us_watch_items"] or 0)
    summary["excluded_non_us"] += int(summary["ignored_non_us_positions"] or 0)

    return {
        "source": "longbridge_cli",
        "scope": "growth_engine_us_universe",
        "classification_rule": GROWTH_UNIVERSE_RULE,
        "classification_policy": _config_payload(active_config),
        "cash_anchor_symbols": sorted(CASH_ANCHOR_SYMBOLS),
        "universe": items,
        "excluded": excluded,
        "summary": summary,
        "write_policy": "read_only_context",
        "source_payloads": {
            "positions": _compact_source_payload(position_payload),
            "watchlist": _compact_source_payload(watchlist_payload),
        },
    }


def format_growth_universe(payload: dict[str, Any]) -> str:
    """Format the Growth universe for CLI/Feishu command output."""

    summary = payload.get("summary") or {}
    lines = [
        "Growth Engine 长桥 universe 读取完成：",
        f"- 入池标的：{summary.get('universe_count', 0)}",
        f"- 持仓来源：{summary.get('source_positions', 0)}",
        f"- 自选来源：{summary.get('source_watch_items', 0)}",
        f"- 期权合约映射底层：{summary.get('option_contracts_mapped', 0)}",
        f"- 普通 ETF：{summary.get('ordinary_etf_count', 0)}，特殊 ETF：{summary.get('special_etf_count', 0)}",
        (
            "- 已排除："
            f"Cash Anchor {summary.get('excluded_cash_anchor', 0)}，"
            f"杠杆 ETF {summary.get('excluded_leveraged_etf', 0)}，"
            f"指数 {summary.get('excluded_index', 0)}，"
            f"非美股 {summary.get('excluded_non_us', 0)}"
        ),
        f"- 规则：{payload.get('classification_rule') or GROWTH_UNIVERSE_RULE}",
        "- 写入策略：只读上下文，不写入本地 Growth 账本。",
    ]
    cache = payload.get("cache") or {}
    if cache:
        cache_state = "命中" if cache.get("hit") else "刷新"
        age = f"，age={cache.get('age_seconds')}s" if cache.get("hit") else ""
        lines.append(f"- 缓存：{cache_state}{age}，ttl={cache.get('ttl_seconds')}s")

    universe = list(payload.get("universe") or [])
    if universe:
        lines.append("")
        lines.append("入池标的：")
        for item in universe[:40]:
            source = ",".join(item.get("source_types") or [])
            group = f" [{','.join(item.get('source_groups') or [])}]" if item.get("source_groups") else ""
            position = " holding" if item.get("has_position") else ""
            subtype = f"/{item.get('asset_subtype')}" if item.get("asset_subtype") else ""
            lines.append(
                f"- {item.get('symbol')} {item.get('name')} "
                f"({item.get('asset_type')}{subtype}, {source}){group}{position}"
            )
        if len(universe) > 40:
            lines.append(f"- ... 其余 {len(universe) - 40} 个略")

    excluded = list(payload.get("excluded") or [])
    if excluded:
        lines.append("")
        lines.append("排除预览：")
        for item in excluded[:20]:
            lines.append(
                f"- {item.get('source_symbol')} {item.get('name')} -> "
                f"{item.get('normalized_symbol') or '-'}：{item.get('reason')}"
            )
    return "\n".join(lines)


def _process_source_row(
    row: dict[str, Any],
    source_type: str,
    universe: dict[str, GrowthUniverseItem],
    excluded: list[dict[str, Any]],
    counters: dict[str, int],
    config: GrowthUniverseConfig,
) -> None:
    source_symbol = str(row.get("symbol") or "").strip().upper()
    if not source_symbol:
        return
    name = str(row.get("name") or row.get("symbol_name") or source_symbol).strip()
    if not _looks_like_us_row(row):
        excluded.append(_excluded_row(row, "", "non_us_security", source_type))
        counters["excluded_non_us"] += 1
        return

    option_underlying = option_underlying_symbol(source_symbol)
    if option_underlying:
        excluded.append(_excluded_row(row, option_underlying, "option_contract_mapped_to_underlying", source_type))
        counters["option_contracts_mapped"] += 1
        symbol = option_underlying
        asset_type = "stock"
        asset_subtype = "option_underlying_stock"
        classification_tags = ["option_underlying"]
        source_type = f"{source_type}_option_underlying"
        counters["option_underlyings_added"] += 1
    else:
        symbol = normalize_us_symbol(source_symbol)
        asset_type, asset_subtype, classification_tags = _classify_asset(symbol, name, config)

    reason = _exclusion_reason(symbol, name, config)
    if reason:
        excluded.append(_excluded_row(row, symbol, reason, source_type))
        if reason == "cash_anchor_symbol":
            counters["excluded_cash_anchor"] += 1
        elif reason == "leveraged_etf":
            counters["excluded_leveraged_etf"] += 1
        elif reason == "index_not_investable":
            counters["excluded_index"] += 1
        return

    candidate = GrowthUniverseItem(
        symbol=symbol,
        name=_display_name(name, source_symbol, symbol),
        asset_type=asset_type,
        asset_subtype=asset_subtype,
        classification_tags=classification_tags,
        source_types=[source_type],
        source_symbols=[source_symbol],
        source_groups=_source_groups(row),
        is_pinned=bool(row.get("is_pinned")),
        has_position=source_type.startswith("longbridge_position"),
        quantity=_optional_float(row.get("quantity")),
        available_quantity=_optional_float(row.get("available_quantity")),
        cost_price=_optional_float(row.get("cost_price")),
        current_price=_optional_float(row.get("current_price")),
        currency=str(row.get("currency") or "USD").strip().upper() or "USD",
        reason=_universe_reason(asset_type, source_type),
    )
    _merge_universe_item(universe, candidate)


def option_underlying_symbol(symbol: str) -> str:
    """Return the normalized underlying symbol for a Longbridge US option symbol."""

    clean = str(symbol or "").strip().upper()
    base = clean[:-3] if clean.endswith(".US") else clean
    match = re.fullmatch(r"([A-Z][A-Z0-9]{0,7})(\d{6})([CP])\d+", base)
    if not match:
        return ""
    return normalize_us_symbol(match.group(1))


def normalize_us_symbol(symbol: str) -> str:
    clean = str(symbol or "").strip().upper()
    if clean.endswith(".US"):
        return clean
    return f"{clean}.US"


def _position_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in ("positions", "excluded_cash_anchor"):
        rows.extend(item for item in payload.get(key) or [] if isinstance(item, dict))
    return rows


def _watchlist_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in ("growth_us_watchlist", "cash_anchor_us_watchlist", "watchlist", "excluded_cash_anchor"):
        rows.extend(item for item in payload.get(key) or [] if isinstance(item, dict))
    return rows


def _looks_like_us_row(row: dict[str, Any]) -> bool:
    market = str(row.get("market") or "").strip().upper()
    symbol = str(row.get("symbol") or "").strip().upper()
    currency = str(row.get("currency") or "").strip().upper()
    return market in {"US", "USA"} or symbol.endswith(".US") or currency == "USD"


def _exclusion_reason(symbol: str, name: str, config: GrowthUniverseConfig) -> str:
    if _is_cash_anchor_symbol(symbol):
        return "cash_anchor_symbol"
    if _is_index_symbol(symbol, name):
        return "index_not_investable"
    if _is_leveraged_etf(symbol, name, config):
        return "leveraged_etf"
    return ""


def _is_cash_anchor_symbol(symbol: str) -> bool:
    clean = symbol.strip().upper()
    base = clean[:-3] if clean.endswith(".US") else clean
    return clean in CASH_ANCHOR_SYMBOLS or base in CASH_ANCHOR_SYMBOLS


def _is_index_symbol(symbol: str, name: str) -> bool:
    clean = symbol.strip().upper()
    base = clean[:-3] if clean.endswith(".US") else clean
    text = f"{symbol} {name}".upper()
    return base.startswith(".") or (" INDEX" in text and "ETF" not in text and "FUND" not in text)


def _is_leveraged_etf(symbol: str, name: str, config: GrowthUniverseConfig) -> bool:
    base = (symbol[:-3] if symbol.endswith(".US") else symbol).upper()
    text = f"{base} {name}".upper()
    if base in config.leveraged_etf_allowlist:
        return False
    if base in config.leveraged_etf_blocklist:
        return True
    patterns = [
        r"\b[2345]X\b",
        r"\b[2345]X\s+(LONG|SHORT|DAILY|BULL|BEAR)\b",
        r"\b(BULL|BEAR)\s+[2345]X\b",
        r"\bULTRAPRO\b",
        r"\bDAILY\s+(BULL|BEAR)\b",
        r"\bLEVERAGED\b",
    ]
    if not any(re.search(pattern, text) for pattern in patterns):
        return False
    return _looks_like_etf(symbol, name) or any(token in text for token in (" SHARES", " ETN", " DAILY "))


def _classify_asset(symbol: str, name: str, config: GrowthUniverseConfig) -> tuple[str, str, list[str]]:
    base = _base_symbol(symbol)
    if _looks_like_etf(symbol, name):
        special = config.special_etf_classifications.get(base) or {}
        subtype = str(special.get("asset_subtype") or "ordinary_etf")
        tags = ["ordinary_etf"]
        if special:
            tags.append("special_etf")
        if base in config.ordinary_etf_allowlist:
            tags.append("ordinary_etf_allowlist")
        return "etf", subtype, tags
    return "stock", "common_stock", ["common_stock"]


def _looks_like_etf(symbol: str, name: str) -> bool:
    text = f"{symbol} {name}".upper()
    return any(token in text for token in (" ETF", " ETN", " FUND", " TRUST"))


def _source_groups(row: dict[str, Any]) -> list[str]:
    group = str(row.get("group_name") or "").strip()
    if not group:
        return []
    return [item.strip() for item in group.split(",") if item.strip()]


def _merge_universe_item(universe: dict[str, GrowthUniverseItem], candidate: GrowthUniverseItem) -> None:
    existing = universe.get(candidate.symbol)
    if existing is None:
        universe[candidate.symbol] = candidate
        return
    existing.name = existing.name or candidate.name
    if existing.asset_type != "stock":
        existing.asset_type = candidate.asset_type
    if existing.asset_subtype == "common_stock" and candidate.asset_subtype != "common_stock":
        existing.asset_subtype = candidate.asset_subtype
    existing.classification_tags = _append_unique(existing.classification_tags, candidate.classification_tags)
    existing.source_types = _append_unique(existing.source_types, candidate.source_types)
    existing.source_symbols = _append_unique(existing.source_symbols, candidate.source_symbols)
    existing.source_groups = _append_unique(existing.source_groups, candidate.source_groups)
    existing.is_pinned = existing.is_pinned or candidate.is_pinned
    existing.has_position = existing.has_position or candidate.has_position
    existing.quantity = existing.quantity if existing.quantity is not None else candidate.quantity
    existing.available_quantity = (
        existing.available_quantity if existing.available_quantity is not None else candidate.available_quantity
    )
    existing.cost_price = existing.cost_price if existing.cost_price is not None else candidate.cost_price
    existing.current_price = existing.current_price if existing.current_price is not None else candidate.current_price
    existing.currency = existing.currency or candidate.currency


def _append_unique(left: list[str], right: list[str]) -> list[str]:
    result = list(left)
    for item in right:
        if item and item not in result:
            result.append(item)
    return result


def _excluded_row(row: dict[str, Any], normalized_symbol: str, reason: str, source_type: str) -> dict[str, Any]:
    return {
        "source_symbol": str(row.get("symbol") or "").strip().upper(),
        "normalized_symbol": normalized_symbol,
        "name": str(row.get("name") or row.get("symbol_name") or "").strip(),
        "market": str(row.get("market") or "").strip(),
        "source_type": source_type,
        "group_name": str(row.get("group_name") or "").strip(),
        "reason": reason,
    }


def _display_name(name: str, source_symbol: str, symbol: str) -> str:
    if option_underlying_symbol(source_symbol):
        return symbol.split(".", 1)[0]
    return name or symbol


def _universe_reason(asset_type: str, source_type: str) -> str:
    if source_type.endswith("option_underlying"):
        return "期权合约只作为底层股票信号，底层股票进入 Growth 美股 universe。"
    if asset_type == "etf":
        return "长桥美股普通 ETF，不属于 Cash Anchor，且不是 2x/3x 杠杆 ETF。"
    return "长桥美股正股，不属于 Cash Anchor 固定现金流标的。"


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _compact_source_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": payload.get("source"),
        "scope": payload.get("scope"),
        "summary": payload.get("summary") or {},
        "write_policy": payload.get("write_policy"),
    }


def load_growth_universe_config() -> GrowthUniverseConfig:
    section = get_config().raw.get("growth_universe") or {}
    if not isinstance(section, dict):
        section = {}
    special = _parse_special_classifications(section.get("special_etf_classifications"))
    merged_special = dict(DEFAULT_SPECIAL_ETF_CLASSIFICATIONS)
    merged_special.update(special)
    ordinary_allowlist = set(merged_special)
    ordinary_allowlist.update(_symbol_set(section.get("ordinary_etf_allowlist")))
    return GrowthUniverseConfig(
        cache_enabled=_bool_value(section.get("cache_enabled"), default=True),
        cache_ttl_seconds=max(0, int(_numeric_value(section.get("cache_ttl_seconds"), DEFAULT_GROWTH_UNIVERSE_CACHE_TTL_SECONDS))),
        leveraged_etf_blocklist=_symbol_set(
            section.get("leveraged_etf_blocklist"),
            default=DEFAULT_LEVERAGED_ETF_SYMBOLS,
        ),
        leveraged_etf_allowlist=_symbol_set(section.get("leveraged_etf_allowlist")),
        ordinary_etf_allowlist=ordinary_allowlist,
        special_etf_classifications=merged_special,
    )


def _read_cached_growth_universe(config: GrowthUniverseConfig) -> dict[str, Any] | None:
    path = _cache_path()
    if not path.exists():
        return None
    try:
        age_seconds = int(datetime.now(timezone.utc).timestamp() - path.stat().st_mtime)
    except OSError:
        return None
    if config.cache_ttl_seconds <= 0 or age_seconds > config.cache_ttl_seconds:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    payload["cache"] = {
        "hit": True,
        "enabled": config.cache_enabled,
        "ttl_seconds": config.cache_ttl_seconds,
        "age_seconds": age_seconds,
        "path": str(path),
    }
    return payload


def _write_cached_growth_universe(payload: dict[str, Any]) -> None:
    path = _cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    except OSError:
        return


def _cache_path() -> Path:
    return RUNTIME_DIR / "cache" / "growth_universe.json"


def _config_payload(config: GrowthUniverseConfig) -> dict[str, Any]:
    return {
        "cache_enabled": config.cache_enabled,
        "cache_ttl_seconds": config.cache_ttl_seconds,
        "leveraged_etf_blocklist": sorted(config.leveraged_etf_blocklist),
        "leveraged_etf_allowlist": sorted(config.leveraged_etf_allowlist),
        "ordinary_etf_allowlist": sorted(config.ordinary_etf_allowlist),
        "special_etf_classifications": config.special_etf_classifications,
    }


def _base_symbol(symbol: str) -> str:
    clean = str(symbol or "").strip().upper()
    return clean[:-3] if clean.endswith(".US") else clean


def _symbol_set(value: Any, *, default: set[str] | None = None) -> set[str]:
    if value in (None, ""):
        return set(default or set())
    if isinstance(value, str):
        parts = re.split(r"[,;\s]+", value)
    elif isinstance(value, (list, tuple, set)):
        parts = [str(item) for item in value]
    else:
        parts = [str(value)]
    result = {_base_symbol(part) for part in parts if str(part).strip()}
    return result or set(default or set())


def _parse_special_classifications(value: Any) -> dict[str, dict[str, str]]:
    if isinstance(value, dict):
        result: dict[str, dict[str, str]] = {}
        for key, raw in value.items():
            base = _base_symbol(str(key))
            if isinstance(raw, dict):
                subtype = str(raw.get("asset_subtype") or "ordinary_etf")
                notes = str(raw.get("notes") or "")
            else:
                subtype = str(raw or "ordinary_etf")
                notes = ""
            result[base] = {"asset_subtype": subtype, "notes": notes}
        return result
    if not isinstance(value, str) or not value.strip():
        return {}
    result: dict[str, dict[str, str]] = {}
    for item in value.split(";"):
        parts = [part.strip() for part in item.split(":", 2)]
        if not parts or not parts[0]:
            continue
        base = _base_symbol(parts[0])
        subtype = parts[1] if len(parts) > 1 and parts[1] else "ordinary_etf"
        notes = parts[2] if len(parts) > 2 else ""
        result[base] = {"asset_subtype": subtype, "notes": notes}
    return result


def _bool_value(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _numeric_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
