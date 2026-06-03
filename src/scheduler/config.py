"""Scheduler configuration loading."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
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
    weekday: int | None = None


@dataclass(frozen=True)
class SchedulerConfig:
    enabled: bool
    timezone: str
    dry_run_by_default: bool
    skip_weekends_for_daily: bool
    skip_holidays: bool
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
        holidays=holidays,
        jobs=jobs,
    )


def is_job_due(job: SchedulerJob, config: SchedulerConfig, now: datetime, *, last_run_dates: set[str] | None = None) -> bool:
    local_now = now.astimezone(config.tzinfo)
    if not job.enabled:
        return False
    if _has_run_today(job, local_now.date(), last_run_dates or set()):
        return False
    if local_now.time().replace(second=0, microsecond=0) < job.run_time:
        return False
    if job.schedule == "daily":
        if config.skip_weekends_for_daily and local_now.weekday() >= 5:
            return False
        return not _is_holiday(job.market, local_now.date(), config)
    if job.schedule == "weekly":
        return job.weekday is not None and local_now.weekday() == job.weekday
    return False


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
        weekday=_parse_weekday(section.get("weekday")),
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


def _is_holiday(market: str, target_date: date, config: SchedulerConfig) -> bool:
    if not config.skip_holidays:
        return False
    market_key = market.upper()
    return target_date.isoformat() in config.holidays.get(market_key, set())


def _has_run_today(job: SchedulerJob, target_date: date, last_run_dates: set[str]) -> bool:
    return run_key(job, target_date) in last_run_dates
