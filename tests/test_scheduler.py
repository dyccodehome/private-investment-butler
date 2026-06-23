from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from src.scheduler import runner
from src.scheduler.config import is_job_due, load_scheduler_config
from src.scheduler.runner import run_job_once


class SchedulerTest(unittest.TestCase):
    def test_load_scheduler_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.yaml"
            config_path.write_text(
                """
scheduler:
  enabled: false
  timezone: Asia/Shanghai
  dry_run_by_default: true
  skip_weekends_for_daily: true
  skip_holidays: true
  holidays:
    CN:
      - "2026-10-01"
  jobs:
    cash_anchor_cn_close_review:
      enabled: true
      type: cash_anchor_cn_close_review
      market: CN
      schedule: daily
      weekdays: [monday, tuesday, wednesday, thursday, friday]
      time: "16:30"
    growth_weekly_review:
      enabled: true
      type: growth_weekly_review
      market: ALL
      schedule: weekly
      weekday: sunday
      time: "20:00"
""",
                encoding="utf-8",
            )

            config = load_scheduler_config(config_path)

        self.assertFalse(config.enabled)
        self.assertTrue(config.dry_run_by_default)
        self.assertEqual(config.timezone, "Asia/Shanghai")
        self.assertTrue(config.use_trading_calendar)
        self.assertEqual({job.name for job in config.jobs}, {"cash_anchor_cn_close_review", "growth_weekly_review"})
        self.assertEqual(config.holidays["CN"], {"2026-10-01"})
        self.assertEqual(_job(config, "cash_anchor_cn_close_review").weekdays, (0, 1, 2, 3, 4))

    def test_daily_job_due_after_run_time_on_weekday(self) -> None:
        config = load_scheduler_config()
        job = _job(config, "cash_anchor_cn_close_review")
        now = datetime(2026, 6, 3, 16, 31, tzinfo=ZoneInfo("Asia/Shanghai"))

        self.assertTrue(is_job_due(job, config, now))

    def test_daily_job_not_due_before_run_time(self) -> None:
        config = load_scheduler_config()
        job = _job(config, "cash_anchor_cn_close_review")
        now = datetime(2026, 6, 3, 16, 19, tzinfo=ZoneInfo("Asia/Shanghai"))

        self.assertFalse(is_job_due(job, config, now))

    def test_daily_job_skips_weekend(self) -> None:
        config = load_scheduler_config()
        job = _job(config, "cash_anchor_cn_close_review")
        now = datetime(2026, 6, 6, 16, 45, tzinfo=ZoneInfo("Asia/Shanghai"))

        self.assertFalse(is_job_due(job, config, now))

    def test_us_close_job_can_run_on_local_saturday(self) -> None:
        config = load_scheduler_config()
        job = _job(config, "growth_us_close_review")
        now = datetime(2026, 6, 6, 6, 30, tzinfo=ZoneInfo("Asia/Shanghai"))

        self.assertTrue(is_job_due(job, config, now))
        self.assertEqual(job.time_timezone, "America/New_York")
        self.assertEqual(job.market_date_offset_days, 0)

    def test_us_premarket_uses_new_york_standard_time(self) -> None:
        config = load_scheduler_config()
        job = _job(config, "growth_us_premarket_review")
        before = datetime(2026, 1, 5, 21, 39, tzinfo=ZoneInfo("Asia/Shanghai"))
        after = datetime(2026, 1, 5, 21, 41, tzinfo=ZoneInfo("Asia/Shanghai"))

        self.assertFalse(is_job_due(job, config, before))
        self.assertTrue(is_job_due(job, config, after))

    def test_us_premarket_uses_new_york_dst_time(self) -> None:
        config = load_scheduler_config()
        job = _job(config, "growth_us_premarket_review")
        before = datetime(2026, 6, 4, 20, 39, tzinfo=ZoneInfo("Asia/Shanghai"))
        after = datetime(2026, 6, 4, 20, 41, tzinfo=ZoneInfo("Asia/Shanghai"))

        self.assertFalse(is_job_due(job, config, before))
        self.assertTrue(is_job_due(job, config, after))

    def test_us_premarket_job_skips_us_market_holiday(self) -> None:
        config = load_scheduler_config()
        job = _job(config, "growth_us_premarket_review")
        now = datetime(2026, 7, 3, 20, 45, tzinfo=ZoneInfo("Asia/Shanghai"))

        self.assertFalse(is_job_due(job, config, now))

    def test_weekly_job_due_on_sunday_after_run_time(self) -> None:
        config = load_scheduler_config()
        job = _job(config, "growth_weekly_review")
        now = datetime(2026, 6, 7, 20, 10, tzinfo=ZoneInfo("Asia/Shanghai"))

        self.assertTrue(is_job_due(job, config, now))

    def test_startup_due_run_keys_only_suppresses_jobs_due_at_start(self) -> None:
        config = load_scheduler_config()
        startup = datetime(2026, 6, 22, 22, 45, tzinfo=ZoneInfo("Asia/Shanghai"))

        skip_keys = runner.startup_due_run_keys(config, startup, existing_run_keys=set())

        self.assertIn("2026-06-22:growth_us_premarket_review", skip_keys)
        self.assertIn("2026-06-22:cash_anchor_cn_close_review", skip_keys)
        self.assertNotIn("2026-06-22:growth_us_close_review", skip_keys)

        later = datetime(2026, 6, 23, 5, 25, tzinfo=ZoneInfo("Asia/Shanghai"))
        due_later = runner.due_jobs(config, later, last_run_dates=skip_keys)

        self.assertIn("growth_us_close_review", {job.name for job in due_later})

    def test_dry_run_once_does_not_call_llm_or_feishu(self) -> None:
        config = load_scheduler_config()
        job = _job(config, "cash_anchor_cn_close_review")
        fake_config = Mock()
        fake_config.messaging.return_value.default_chat_id = "oc_test"

        with patch("src.scheduler.runner.get_config", return_value=fake_config), patch(
            "src.scheduler.runner.run_scheduled_review_job"
        ) as run_scheduled_review_job, patch("src.scheduler.runner.communication_gate.send") as send:
            run_scheduled_review_job.return_value = "[试运行] 成长引擎"
            reply = run_job_once(job, dry_run=True)

        self.assertIn("试运行", reply)
        run_scheduled_review_job.assert_called_once_with(
            "cash_anchor_cn_close_review",
            chat_id="oc_test",
            dry_run=True,
            as_of=None,
        )
        send.assert_not_called()

    def test_cash_anchor_premarket_review_job_dry_run(self) -> None:
        config = load_scheduler_config()
        job = _job(config, "cash_anchor_cn_premarket_review")
        fake_config = Mock()
        fake_config.messaging.return_value.default_chat_id = "oc_test"

        with patch("src.scheduler.runner.get_config", return_value=fake_config), patch(
            "src.scheduler.runner.run_scheduled_review_job"
        ) as run_scheduled_review_job, patch("src.scheduler.runner.communication_gate.send") as send:
            run_scheduled_review_job.return_value = "[试运行] 现金锚点"
            reply = run_job_once(job, dry_run=True)

        self.assertIn("试运行", reply)
        run_scheduled_review_job.assert_called_once_with(
            "cash_anchor_cn_premarket_review",
            chat_id="oc_test",
            dry_run=True,
            as_of=None,
        )
        send.assert_not_called()

    def test_run_once_can_suppress_direct_send_for_command_handler(self) -> None:
        config = load_scheduler_config()
        job = _job(config, "growth_us_close_review")
        fake_config = Mock()
        fake_config.messaging.return_value.default_chat_id = "oc_test"

        with patch("src.scheduler.runner.get_config", return_value=fake_config), patch(
            "src.scheduler.runner.run_scheduled_review_job", return_value="正式结果"
        ), patch("src.scheduler.runner.communication_gate.send") as send:
            reply = run_job_once(job, dry_run=False, send_result=False)

        self.assertEqual(reply, "正式结果")
        send.assert_not_called()

    def test_run_once_skips_when_same_job_lock_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = load_scheduler_config()
            job = _job(config, "growth_us_close_review")
            fake_config = Mock()
            fake_config.messaging.return_value.default_chat_id = "oc_test"
            lock_dir = Path(tmp) / "locks"

            with patch.object(runner, "LOCK_DIR", lock_dir):
                lock_dir.mkdir(parents=True, exist_ok=True)
                runner._job_lock_path(job).write_text("busy", encoding="utf-8")
                with patch("src.scheduler.runner.get_config", return_value=fake_config), patch(
                    "src.scheduler.runner.run_scheduled_review_job"
                ) as run_scheduled_review_job, patch("src.scheduler.runner.communication_gate.send") as send:
                    reply = run_job_once(job, dry_run=False)

            self.assertIn("已跳过重复触发", reply)
            run_scheduled_review_job.assert_not_called()
            send.assert_not_called()

    def test_execute_and_record_uses_job_timezone_run_date_as_review_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = load_scheduler_config()
            job = _job(config, "growth_us_close_review")
            fake_config = Mock()
            fake_config.messaging.return_value.default_chat_id = ""
            runs_path = Path(tmp) / "runs.jsonl"
            now = datetime(2026, 6, 23, 5, 25, tzinfo=ZoneInfo("Asia/Shanghai"))

            with patch("src.scheduler.runner.get_config", return_value=fake_config), patch(
                "src.scheduler.runner.run_scheduled_review_job", return_value="正式结果"
            ) as run_scheduled_review_job, patch.object(runner, "STATE_DIR", Path(tmp)), patch.object(
                runner, "RUNS_PATH", runs_path
            ):
                runner._execute_and_record(job, config, now, dry_run=False)

        run_scheduled_review_job.assert_called_once_with(
            "growth_us_close_review",
            chat_id=None,
            dry_run=False,
            as_of=datetime(2026, 6, 22, tzinfo=ZoneInfo("America/New_York")).date(),
        )

    def test_failed_job_is_logged_and_sends_error_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = load_scheduler_config()
            job = _job(config, "growth_us_close_review")
            fake_config = Mock()
            fake_config.messaging.return_value.default_chat_id = "oc_test"
            runs_path = Path(tmp) / "runs.jsonl"

            with patch("src.scheduler.runner.get_config", return_value=fake_config), patch(
                "src.scheduler.runner.run_job_once", side_effect=RuntimeError("boom")
            ), patch("src.scheduler.runner.communication_gate.send") as send, patch.object(
                runner, "STATE_DIR", Path(tmp)
            ), patch.object(
                runner, "RUNS_PATH", runs_path
            ):
                runner._execute_and_record(
                    job,
                    config,
                    datetime(2026, 6, 3, 16, 31, tzinfo=ZoneInfo("Asia/Shanghai")),
                    dry_run=False,
                )

            log = runs_path.read_text(encoding="utf-8")

        self.assertIn('"status": "error"', log)
        self.assertIn('"error": "boom"', log)
        send.assert_called_once()
        self.assertIn("定时任务失败", send.call_args.args[1])

    def test_duplicate_job_skip_is_logged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = load_scheduler_config()
            job = _job(config, "growth_us_close_review")
            runs_path = Path(tmp) / "runs.jsonl"

            with patch(
                "src.scheduler.runner.run_job_once",
                return_value=f"定时任务正在运行，已跳过重复触发：{job.name}",
            ), patch.object(
                runner, "STATE_DIR", Path(tmp)
            ), patch.object(
                runner, "RUNS_PATH", runs_path
            ):
                runner._execute_and_record(
                    job,
                    config,
                    datetime(2026, 6, 3, 16, 31, tzinfo=ZoneInfo("Asia/Shanghai")),
                    dry_run=False,
                )

            log = runs_path.read_text(encoding="utf-8")

        self.assertIn('"status": "skipped"', log)
        self.assertIn("已跳过重复触发", log)


def _job(config, name: str):
    return next(job for job in config.jobs if job.name == name)


if __name__ == "__main__":
    unittest.main()
