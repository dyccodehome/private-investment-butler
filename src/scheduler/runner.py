"""Scheduler runner and job dispatch."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from src import communication_gate
from src.app_config import get_config
from src.init import RUNTIME_DIR
from src.scheduler.config import SchedulerConfig, SchedulerJob, is_job_due, load_scheduler_config, run_key, scheduled_run_date
from src.scheduler.jobs import (
    is_scheduled_review_job_type,
    run_cash_anchor_cn_dividend_review_job,
    run_cash_anchor_us_income_distribution_job,
    run_growth_daily_review_job,
    run_growth_weekly_review_job,
    run_scheduled_review_job,
)


STATE_DIR = RUNTIME_DIR / "scheduler"
RUNS_PATH = STATE_DIR / "runs.jsonl"
LOCK_DIR = STATE_DIR / "locks"
JOB_LOCK_STALE_SECONDS = 6 * 60 * 60


def due_jobs(config: SchedulerConfig, now: datetime, *, last_run_dates: set[str] | None = None) -> list[SchedulerJob]:
    return [job for job in config.jobs if is_job_due(job, config, now, last_run_dates=last_run_dates)]


def run_job_once(
    job: SchedulerJob,
    *,
    chat_id: str | None = None,
    dry_run: bool = True,
    send_result: bool = True,
) -> str:
    target_chat_id = chat_id or get_config().messaging().default_chat_id
    job_lock = _acquire_job_lock(job)
    if not job_lock.acquired:
        return f"定时任务正在运行，已跳过重复触发：{job.name}"
    try:
        if is_scheduled_review_job_type(job.job_type):
            result = run_scheduled_review_job(job.job_type, chat_id=target_chat_id or None, dry_run=dry_run)
        elif job.job_type == "growth_daily_review":
            result = run_growth_daily_review_job(job.market, chat_id=target_chat_id or None, dry_run=dry_run)
        elif job.job_type == "growth_weekly_review":
            result = run_growth_weekly_review_job(chat_id=target_chat_id or None, dry_run=dry_run)
        elif job.job_type == "cash_anchor_cn_dividend_review":
            result = run_cash_anchor_cn_dividend_review_job(chat_id=target_chat_id or None, dry_run=dry_run)
        elif job.job_type == "cash_anchor_us_income_distribution_sync":
            result = run_cash_anchor_us_income_distribution_job(chat_id=target_chat_id or None, dry_run=dry_run)
        else:
            raise ValueError(f"未知定时任务类型：{job.job_type}")
    finally:
        job_lock.release()

    if target_chat_id and not dry_run and send_result:
        communication_gate.send(target_chat_id, result)
    return result


def run_loop(*, dry_run: bool | None = None, poll_seconds: int = 60, skip_existing_due: bool = False) -> None:
    config = load_scheduler_config()
    effective_dry_run = config.dry_run_by_default if dry_run is None else dry_run
    print(
        "Scheduler started: "
        f"enabled={config.enabled} timezone={config.timezone} dry_run={effective_dry_run} "
        f"skip_existing_due={skip_existing_due}",
        flush=True,
    )
    if not config.enabled:
        print("Scheduler is disabled in config.yaml. Use --list or enable scheduler.enabled before running loop.", flush=True)
        return

    startup_skip_keys: set[str] = set()
    if skip_existing_due:
        now = datetime.now(tz=config.tzinfo)
        startup_skip_keys = startup_due_run_keys(config, now, existing_run_keys=read_run_keys())
        if startup_skip_keys:
            print(
                "Scheduler startup skipped already-due jobs: "
                + ", ".join(sorted(startup_skip_keys)),
                flush=True,
            )

    while True:
        now = datetime.now(tz=config.tzinfo)
        last_runs = read_run_keys() | startup_skip_keys
        for job in due_jobs(config, now, last_run_dates=last_runs):
            _execute_and_record(job, config, now, dry_run=effective_dry_run)
        time.sleep(poll_seconds)


def startup_due_run_keys(
    config: SchedulerConfig,
    now: datetime,
    *,
    existing_run_keys: set[str] | None = None,
) -> set[str]:
    """Return due run keys to suppress when starting a long-running scheduler late."""

    existing = existing_run_keys or set()
    return {
        run_key(job, scheduled_run_date(job, config, now))
        for job in due_jobs(config, now, last_run_dates=existing)
    }


def read_run_keys(path: Path = RUNS_PATH) -> set[str]:
    if not path.exists():
        return set()
    keys: set[str] = set()
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = str(row.get("run_key") or "")
            if key:
                keys.add(key)
    return keys


def _execute_and_record(job: SchedulerJob, config: SchedulerConfig, now: datetime, *, dry_run: bool) -> None:
    status = "ok"
    error = ""
    try:
        result = run_job_once(job, dry_run=dry_run)
        if _is_duplicate_run_skip(result):
            status = "skipped"
    except Exception as exc:
        status = "error"
        error = str(exc)
        result = f"定时任务失败：{job.name}\n{error}"
        chat_id = get_config().messaging().default_chat_id
        if chat_id:
            communication_gate.send(chat_id, result)
    _append_run_log(job, config, now, status=status, result=result, error=error, dry_run=dry_run)


def _append_run_log(
    job: SchedulerJob,
    config: SchedulerConfig,
    now: datetime,
    *,
    status: str,
    result: str,
    error: str,
    dry_run: bool,
) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    local_now = now.astimezone(config.tzinfo)
    row = {
        "run_key": run_key(job, scheduled_run_date(job, config, now)),
        "job": job.name,
        "job_type": job.job_type,
        "market": job.market,
        "status": status,
        "dry_run": dry_run,
        "error": error,
        "result_preview": result[:500],
        "created_at": local_now.isoformat(),
    }
    with RUNS_PATH.open("a", encoding="utf-8") as file:
        file.write(json.dumps(row, ensure_ascii=False) + "\n")


@dataclass
class _JobExecutionLock:
    path: Path
    acquired: bool

    def release(self) -> None:
        if not self.acquired:
            return
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def _acquire_job_lock(job: SchedulerJob, *, stale_seconds: int = JOB_LOCK_STALE_SECONDS) -> _JobExecutionLock:
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    path = _job_lock_path(job)
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if _is_stale_lock(path, stale_seconds=stale_seconds):
                try:
                    path.unlink()
                    continue
                except FileNotFoundError:
                    continue
            return _JobExecutionLock(path=path, acquired=False)
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(
                json.dumps(
                    {
                        "job": job.name,
                        "job_type": job.job_type,
                        "market": job.market,
                        "pid": os.getpid(),
                        "created_at": datetime.now().astimezone().isoformat(),
                    },
                    ensure_ascii=False,
                )
            )
        return _JobExecutionLock(path=path, acquired=True)
    return _JobExecutionLock(path=path, acquired=False)


def _job_lock_path(job: SchedulerJob) -> Path:
    safe_name = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in job.name)
    return LOCK_DIR / f"{safe_name}.lock"


def _is_stale_lock(path: Path, *, stale_seconds: int) -> bool:
    if stale_seconds <= 0:
        return False
    try:
        return time.time() - path.stat().st_mtime > stale_seconds
    except FileNotFoundError:
        return True


def _is_duplicate_run_skip(result: str) -> bool:
    return result.startswith("定时任务正在运行，已跳过重复触发：")
