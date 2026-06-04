"""A/CN and US market phase context.

This module is intentionally small and deterministic. It does not try to be a
full exchange-calendar implementation; holiday gaps are reported as data
limitations so the auditor can cap confidence when needed.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo


CN_TZ = ZoneInfo("Asia/Shanghai")
US_TZ = ZoneInfo("America/New_York")


def build_market_phase_context(
    market: str,
    *,
    now: datetime | None = None,
    trigger_source: str = "pipeline",
) -> dict[str, Any]:
    """Return phase context for CN/US markets only."""

    clean_market = _normalize_market(market)
    tz = US_TZ if clean_market == "US" else CN_TZ
    local_now = (now or datetime.now(tz=tz)).astimezone(tz)
    is_weekday = local_now.weekday() < 5

    if clean_market == "US":
        phase = _session_phase(
            local_now,
            morning_start=time(9, 30),
            morning_end=time(16, 0),
        )
        session_windows = ["09:30-16:00 America/New_York"]
    else:
        phase = _cn_phase(local_now)
        session_windows = ["09:30-11:30 Asia/Shanghai", "13:00-15:00 Asia/Shanghai"]

    if not is_weekday:
        phase = "non_trading"

    warnings = [
        "节假日交易日历尚未自动接入，当前仅按工作日和常规交易时段判断。"
    ]
    return {
        "market": clean_market,
        "phase": phase,
        "market_local_time": local_now.replace(microsecond=0).isoformat(),
        "session_date": local_now.date().isoformat(),
        "is_trading_day": is_weekday,
        "is_market_open_now": phase == "intraday",
        "is_partial_bar": phase in {"intraday", "lunch_break"},
        "trigger_source": trigger_source,
        "session_windows": session_windows,
        "warnings": warnings,
    }


def _normalize_market(market: str) -> str:
    clean = str(market or "").strip().upper()
    if clean in {"CN", "A", "ASHARE", "A_SHARE", "A股"}:
        return "CN"
    if clean in {"US", "USA", "美股"}:
        return "US"
    return "US" if clean == "US" else "CN"


def _cn_phase(local_now: datetime) -> str:
    t = local_now.time()
    if t < time(9, 30):
        return "premarket"
    if time(9, 30) <= t < time(11, 30):
        return "intraday"
    if time(11, 30) <= t < time(13, 0):
        return "lunch_break"
    if time(13, 0) <= t < time(15, 0):
        return "intraday"
    return "postmarket"


def _session_phase(
    local_now: datetime,
    *,
    morning_start: time,
    morning_end: time,
) -> str:
    t = local_now.time()
    if t < morning_start:
        return "premarket"
    if morning_start <= t < morning_end:
        return "intraday"
    return "postmarket"
