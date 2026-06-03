#!/usr/bin/env python3
"""Inspect or run scheduled review jobs.

Use --list to inspect configured jobs, --due-now to check due jobs, or
--run-loop to follow the execution policy in config.yaml. For one-off manual
runs, --run-once still defaults to dry-run unless --execute is provided.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.scheduler.config import load_scheduler_config
from src.scheduler.runner import due_jobs, read_run_keys, run_job_once, run_loop


def main() -> None:
    parser = argparse.ArgumentParser(description="Scheduled review job runner.")
    parser.add_argument("--list", action="store_true", help="List configured scheduler jobs.")
    parser.add_argument("--due-now", action="store_true", help="Print jobs due at the current time.")
    parser.add_argument("--run-once", default="", help="Run one configured job by name. Defaults to dry-run.")
    parser.add_argument("--run-loop", action="store_true", help="Start scheduler loop. Requires scheduler.enabled=true.")
    parser.add_argument("--execute", action="store_true", help="Execute real job logic instead of dry-run.")
    parser.add_argument("--poll-seconds", type=int, default=60, help="Loop poll interval.")
    args = parser.parse_args()

    config = load_scheduler_config()
    if args.list:
        _print_jobs(config)
        return
    if args.due_now:
        now = datetime.now(tz=config.tzinfo)
        for job in due_jobs(config, now, last_run_dates=read_run_keys()):
            print(job.name)
        return
    if args.run_once:
        job = next((item for item in config.jobs if item.name == args.run_once), None)
        if job is None:
            raise SystemExit(f"未知任务：{args.run_once}")
        print(run_job_once(job, dry_run=not args.execute))
        return
    if args.run_loop:
        run_loop(dry_run=False if args.execute else None, poll_seconds=args.poll_seconds)
        return
    _print_jobs(config)


def _print_jobs(config) -> None:
    print(f"Scheduler enabled={config.enabled} timezone={config.timezone} dry_run_by_default={config.dry_run_by_default}")
    for job in config.jobs:
        weekday = "" if job.weekday is None else f" weekday={job.weekday}"
        print(
            f"- {job.name}: enabled={job.enabled} type={job.job_type} "
            f"market={job.market} schedule={job.schedule} time={job.run_time.strftime('%H:%M')}{weekday}"
        )


if __name__ == "__main__":
    main()
