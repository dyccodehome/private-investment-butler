"""Scheduler configuration loading."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from src.init import PROJECT_ROOT


CONFIG_PATH = PROJECT_ROOT / "config.yaml"
WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


@dataclass(frozen=True)
class SchedulerJob:
    name: str
    enabled: bool
    job_type: str
    market: str
    schedule: str
    run_time: time
    time_timezone: str | None = None
    weekday: int | None = None
    weekdays: tuple[int, ...] | None = None
    market_date_offset_days: int = 0


@dataclass(frozen=True)
class SchedulerConfig:
    enabled: bool
    timezone: str
    dry_run_by_default: bool
    skip_weekends_for_daily: bool
    skip_holidays: bool
    use_trading_calendar: bool
    holidays: dict[str, set[str]]
    jobs: tuple[SchedulerJob, ...]

    @property
    def tzinfo(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


def load_scheduler_config(path: Path = CONFIG_PATH) -> SchedulerConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    section = raw.get("scheduler") or {}
    jobs = tuple(_parse_job(name, value or {}) for name, value in (section.get("jobs") or {}).items())
    holidays = {
        str(market).upper(): {str(item) for item in values or []}
        for market, values in (section.get("holidays") or {}).items()
    }
    return SchedulerConfig(
        enabled=bool(section.get("enabled", False)),
        timezone=str(section.get("timezone") or "Asia/Shanghai"),
        dry_run_by_default=bool(section.get("dry_run_by_default", True)),
        skip_weekends_for_daily=bool(section.get("skip_weekends_for_daily", True)),
        skip_holidays=bool(section.get("skip_holidays", True)),
        use_trading_calendar=bool(section.get("use_trading_calendar", True)),
        holidays=holidays,
        jobs=jobs,
    )


def is_job_due(job: SchedulerJob, config: SchedulerConfig, now: datetime, *, last_run_dates: set[str] | None = None) -> bool:
    schedule_now = now.astimezone(_job_tzinfo(job, config))
    if not job.enabled:
        return False
    if _has_run_today(job, schedule_now.date(), last_run_dates or set()):
        return False
    if schedule_now.time().replace(second=0, microsecond=0) < job.run_time:
        return False
    if job.schedule == "daily":
        if job.weekdays is not None:
            if schedule_now.weekday() not in job.weekdays:
                return False
        elif config.skip_weekends_for_daily and schedule_now.weekday() >= 5:
            return False
        market_date = schedule_now.date() + timedelta(days=job.market_date_offset_days)
        if config.use_trading_calendar and job.market.upper() != "ALL":
            from src.trading_calendar import is_trading_day

            manual_holidays = config.holidays.get(job.market.upper(), set()) if config.skip_holidays else set()
            return is_trading_day(job.market, market_date, manual_holidays=manual_holidays)
        return not _is_holiday(job.market, market_date, config)
    if job.schedule == "weekly":
        return job.weekday is not None and schedule_now.weekday() == job.weekday
    return False


def scheduled_run_date(job: SchedulerJob, config: SchedulerConfig, now: datetime) -> date:
    """Return the date namespace used for once-per-day run keys."""

    return now.astimezone(_job_tzinfo(job, config)).date()


def run_key(job: SchedulerJob, target_date: date) -> str:
    return f"{target_date.isoformat()}:{job.name}"


def _parse_job(name: str, section: dict[str, Any]) -> SchedulerJob:
    return SchedulerJob(
        name=name,
        enabled=bool(section.get("enabled", True)),
        job_type=str(section.get("type") or name),
        market=str(section.get("market") or ""),
        schedule=str(section.get("schedule") or "daily").lower(),
        run_time=_parse_time(str(section.get("time") or "00:00")),
        time_timezone=_parse_optional_timezone(section.get("time_timezone") or section.get("market_timezone")),
        weekday=_parse_weekday(section.get("weekday")),
        weekdays=_parse_weekdays(section.get("weekdays")),
        market_date_offset_days=int(section.get("market_date_offset_days") or 0),
    )


def _parse_time(value: str) -> time:
    hour, minute = value.split(":", 1)
    return time(hour=int(hour), minute=int(minute))


def _parse_weekday(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    return WEEKDAYS[str(value).strip().lower()]


def _parse_weekdays(value: Any) -> tuple[int, ...] | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        raw_items = [item.strip() for item in value.split(",") if item.strip()]
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raw_items = [value]
    weekdays: list[int] = []
    for item in raw_items:
        if isinstance(item, int):
            weekdays.append(item)
        else:
            weekdays.append(WEEKDAYS[str(item).strip().lower()])
    return tuple(weekdays)


def _parse_optional_timezone(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _job_tzinfo(job: SchedulerJob, config: SchedulerConfig) -> ZoneInfo:
    return ZoneInfo(job.time_timezone) if job.time_timezone else config.tzinfo


def _is_holiday(market: str, target_date: date, config: SchedulerConfig) -> bool:
    if not config.skip_holidays:
        return False
    market_key = market.upper()
    return target_date.isoformat() in config.holidays.get(market_key, set())


def _has_run_today(job: SchedulerJob, target_date: date, last_run_dates: set[str]) -> bool:
    return run_key(job, target_date) in last_run_dates
