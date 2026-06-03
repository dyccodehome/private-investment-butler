"""Scheduler runner and job dispatch."""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from src import communication_gate
from src.app_config import get_config
from src.init import RUNTIME_DIR
from src.scheduler.config import SchedulerConfig, SchedulerJob, is_job_due, load_scheduler_config, run_key
from src.scheduler.jobs import run_growth_daily_review_job, run_growth_weekly_review_job


STATE_DIR = RUNTIME_DIR / "scheduler"
RUNS_PATH = STATE_DIR / "runs.jsonl"


def due_jobs(config: SchedulerConfig, now: datetime, *, last_run_dates: set[str] | None = None) -> list[SchedulerJob]:
    return [job for job in config.jobs if is_job_due(job, config, now, last_run_dates=last_run_dates)]


def run_job_once(job: SchedulerJob, *, chat_id: str | None = None, dry_run: bool = True) -> str:
    target_chat_id = chat_id or get_config().messaging().default_chat_id
    if job.job_type == "growth_daily_review":
        result = run_growth_daily_review_job(job.market, chat_id=target_chat_id or None, dry_run=dry_run)
    elif job.job_type == "growth_weekly_review":
        result = run_growth_weekly_review_job(chat_id=target_chat_id or None, dry_run=dry_run)
    else:
        raise ValueError(f"未知定时任务类型：{job.job_type}")

    if target_chat_id and not dry_run:
        communication_gate.send(target_chat_id, result)
    return result


def run_loop(*, dry_run: bool | None = None, poll_seconds: int = 60) -> None:
    config = load_scheduler_config()
    effective_dry_run = config.dry_run_by_default if dry_run is None else dry_run
    print(
        "Scheduler started: "
        f"enabled={config.enabled} timezone={config.timezone} dry_run={effective_dry_run}",
        flush=True,
    )
    if not config.enabled:
        print("Scheduler is disabled in config.yaml. Use --list or enable scheduler.enabled before running loop.", flush=True)
        return

    while True:
        now = datetime.now(tz=config.tzinfo)
        last_runs = read_run_keys()
        for job in due_jobs(config, now, last_run_dates=last_runs):
            _execute_and_record(job, config, now, dry_run=effective_dry_run)
        time.sleep(poll_seconds)


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
        "run_key": run_key(job, local_now.date()),
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
