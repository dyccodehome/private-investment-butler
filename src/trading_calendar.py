"""Local trading calendar utilities.

The scheduler needs market trading dates, not just local weekdays. This module
keeps that logic local-first: cached calendars are authoritative, US calendars
can be generated deterministically, and CN calendars can be refreshed from
AkShare when the user explicitly runs the refresh script.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from src.init import RUNTIME_DIR


CALENDAR_DIR = RUNTIME_DIR / "trading_calendar"
SCHEMA_VERSION = 1


def is_trading_day(
    market: str,
    target_date: date,
    *,
    manual_holidays: set[str] | None = None,
) -> bool:
    """Return whether target_date is a trading day for one market.

    Manual holidays always override generated or cached calendars. When a CN
    cache does not exist, the safe local fallback is weekdays minus manual
    holidays. Use scripts/refresh_trading_calendar.py to create the annual CN
    cache from AkShare.
    """

    clean_market = normalize_market(market)
    if clean_market == "ALL":
        return True
    holiday_set = manual_holidays or set()
    iso = target_date.isoformat()
    if iso in holiday_set:
        return False
    if target_date.weekday() >= 5:
        return False

    payload = load_trading_calendar(clean_market, target_date.year)
    if payload is None and clean_market == "US":
        payload = build_trading_calendar(clean_market, target_date.year, allow_fetch=False)
    if payload is None:
        return True
    return iso in set(payload.get("trading_days") or [])


def build_trading_calendar(
    market: str,
    year: int,
    *,
    refresh: bool = False,
    allow_fetch: bool = True,
) -> dict[str, Any]:
    """Build or load one annual trading calendar payload."""

    clean_market = normalize_market(market)
    if clean_market == "ALL":
        raise ValueError("ALL 没有单独交易日历。")
    cached = load_trading_calendar(clean_market, year)
    if cached is not None and not refresh:
        return cached

    warnings: list[str] = []
    if clean_market == "US":
        trading_days = _generate_us_trading_days(year)
        source = "us_market_rules"
    elif clean_market == "CN" and allow_fetch:
        try:
            trading_days = _fetch_cn_trading_days_from_akshare(year)
            source = "akshare_tool_trade_date_hist_sina"
            if not trading_days:
                raise RuntimeError("AkShare 没有返回交易日。")
        except Exception as exc:
            trading_days = _generate_weekday_fallback(year)
            source = "weekday_fallback"
            warnings.append(f"A 股交易日历刷新失败，已回退到工作日：{exc}")
    else:
        trading_days = _generate_weekday_fallback(year)
        source = "weekday_fallback"
        if clean_market == "CN":
            warnings.append("A 股交易日历缓存不存在；当前使用工作日回退。")

    payload = _calendar_payload(
        market=clean_market,
        year=year,
        source=source,
        trading_days=trading_days,
        warnings=warnings,
    )
    save_trading_calendar(payload)
    return payload


def load_trading_calendar(market: str, year: int) -> dict[str, Any] | None:
    path = calendar_path(market, year)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if int(payload.get("schema_version") or 0) != SCHEMA_VERSION:
        return None
    if normalize_market(str(payload.get("market") or "")) != normalize_market(market):
        return None
    if int(payload.get("year") or 0) != int(year):
        return None
    return payload


def save_trading_calendar(payload: dict[str, Any]) -> Path:
    market = normalize_market(str(payload.get("market") or ""))
    year = int(payload.get("year") or 0)
    if not market or not year:
        raise ValueError("交易日历缺少 market/year。")
    CALENDAR_DIR.mkdir(parents=True, exist_ok=True)
    path = calendar_path(market, year)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def calendar_path(market: str, year: int) -> Path:
    return CALENDAR_DIR / f"{normalize_market(market)}_{int(year)}.json"


def normalize_market(market: str) -> str:
    clean = str(market or "").strip().upper()
    if clean in {"A", "A股", "CN", "CHINA", "ASHARE", "A_SHARE"}:
        return "CN"
    if clean in {"US", "USA", "美股", "NYSE", "NASDAQ"}:
        return "US"
    if clean == "ALL":
        return "ALL"
    return clean


def _calendar_payload(
    *,
    market: str,
    year: int,
    source: str,
    trading_days: list[date],
    warnings: list[str],
) -> dict[str, Any]:
    unique_days = sorted({item for item in trading_days if item.year == year})
    return {
        "schema_version": SCHEMA_VERSION,
        "market": market,
        "year": year,
        "source": source,
        "generated_at": datetime.now().replace(microsecond=0).isoformat(),
        "trading_days": [item.isoformat() for item in unique_days],
        "warnings": warnings,
    }


def _generate_weekday_fallback(year: int) -> list[date]:
    current = date(year, 1, 1)
    end = date(year, 12, 31)
    result: list[date] = []
    while current <= end:
        if current.weekday() < 5:
            result.append(current)
        current += timedelta(days=1)
    return result


def _generate_us_trading_days(year: int) -> list[date]:
    holidays = _us_market_holidays(year)
    return [item for item in _generate_weekday_fallback(year) if item not in holidays]


def _us_market_holidays(year: int) -> set[date]:
    holidays: set[date] = set()
    candidates = [
        date(year, 1, 1),
        _nth_weekday(year, 1, 0, 3),
        _nth_weekday(year, 2, 0, 3),
        _easter_sunday(year) - timedelta(days=2),
        _last_weekday(year, 5, 0),
        date(year, 6, 19),
        date(year, 7, 4),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 11, 3, 4),
        date(year, 12, 25),
    ]
    # Include next year's New Year observed on Dec 31 when applicable.
    candidates.append(date(year + 1, 1, 1))
    for item in candidates:
        observed = _observed_market_holiday(item)
        if observed.year == year:
            holidays.add(observed)
    return holidays


def _observed_market_holiday(day: date) -> date:
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def _nth_weekday(year: int, month: int, weekday: int, nth: int) -> date:
    current = date(year, month, 1)
    while current.weekday() != weekday:
        current += timedelta(days=1)
    return current + timedelta(days=7 * (nth - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    current = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)
    while current.weekday() != weekday:
        current -= timedelta(days=1)
    return current


def _easter_sunday(year: int) -> date:
    # Anonymous Gregorian algorithm.
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _fetch_cn_trading_days_from_akshare(year: int) -> list[date]:
    import akshare as ak  # type: ignore

    frame = ak.tool_trade_date_hist_sina()
    records = frame.to_dict(orient="records")
    result: list[date] = []
    for row in records:
        value = row.get("trade_date") or row.get("交易日") or row.get("date")
        parsed = _parse_date(value)
        if parsed and parsed.year == year:
            result.append(parsed)
    return result


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if hasattr(value, "date"):
        maybe_date = value.date()
        if isinstance(maybe_date, date):
            return maybe_date
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None
