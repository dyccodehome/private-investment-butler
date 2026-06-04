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
    growth_cn_daily_review:
      enabled: true
      type: growth_daily_review
      market: CN
      schedule: daily
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
        self.assertEqual({job.name for job in config.jobs}, {"growth_cn_daily_review", "growth_weekly_review"})
        self.assertEqual(config.holidays["CN"], {"2026-10-01"})

    def test_daily_job_due_after_run_time_on_weekday(self) -> None:
        config = load_scheduler_config()
        job = _job(config, "growth_cn_daily_review")
        now = datetime(2026, 6, 3, 16, 31, tzinfo=ZoneInfo("Asia/Shanghai"))

        self.assertTrue(is_job_due(job, config, now))

    def test_daily_job_not_due_before_run_time(self) -> None:
        config = load_scheduler_config()
        job = _job(config, "growth_cn_daily_review")
        now = datetime(2026, 6, 3, 16, 29, tzinfo=ZoneInfo("Asia/Shanghai"))

        self.assertFalse(is_job_due(job, config, now))

    def test_daily_job_skips_weekend(self) -> None:
        config = load_scheduler_config()
        job = _job(config, "growth_cn_daily_review")
        now = datetime(2026, 6, 6, 16, 45, tzinfo=ZoneInfo("Asia/Shanghai"))

        self.assertFalse(is_job_due(job, config, now))

    def test_weekly_job_due_on_sunday_after_run_time(self) -> None:
        config = load_scheduler_config()
        job = _job(config, "growth_weekly_review")
        now = datetime(2026, 6, 7, 20, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

        self.assertTrue(is_job_due(job, config, now))

    def test_dry_run_once_does_not_call_llm_or_feishu(self) -> None:
        config = load_scheduler_config()
        job = _job(config, "growth_cn_daily_review")
        fake_config = Mock()
        fake_config.messaging.return_value.default_chat_id = "oc_test"

        with patch("src.scheduler.runner.get_config", return_value=fake_config), patch(
            "src.scheduler.jobs.review_growth_daily"
        ) as review_growth_daily, patch("src.scheduler.runner.communication_gate.send") as send:
            reply = run_job_once(job, dry_run=True)

        self.assertIn("试运行", reply)
        review_growth_daily.assert_not_called()
        send.assert_not_called()

    def test_cash_anchor_dividend_review_job_dry_run(self) -> None:
        config = load_scheduler_config()
        job = _job(config, "cash_anchor_cn_dividend_review")
        fake_config = Mock()
        fake_config.messaging.return_value.default_chat_id = "oc_test"

        with patch("src.scheduler.runner.get_config", return_value=fake_config), patch(
            "src.scheduler.jobs.review_cn_dividend_disclosures"
        ) as review_cn_dividend_disclosures, patch("src.scheduler.runner.communication_gate.send") as send:
            reply = run_job_once(job, dry_run=True)

        self.assertIn("现金锚点境内红利财报核验", reply)
        review_cn_dividend_disclosures.assert_not_called()
        send.assert_not_called()

    def test_cash_anchor_us_income_distribution_job_dry_run(self) -> None:
        config = load_scheduler_config()
        job = _job(config, "cash_anchor_us_income_distribution_sync")
        fake_config = Mock()
        fake_config.messaging.return_value.default_chat_id = "oc_test"

        with patch("src.scheduler.runner.get_config", return_value=fake_config), patch(
            "src.scheduler.jobs.sync_longbridge_us_income_distributions"
        ) as sync_longbridge_us_income_distributions, patch("src.scheduler.runner.communication_gate.send") as send:
            reply = run_job_once(job, dry_run=True)

        self.assertIn("美元收益分配同步", reply)
        sync_longbridge_us_income_distributions.assert_not_called()
        send.assert_not_called()

    def test_failed_job_is_logged_and_sends_error_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = load_scheduler_config()
            job = _job(config, "growth_cn_daily_review")
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


def _job(config, name: str):
    return next(job for job in config.jobs if job.name == name)


if __name__ == "__main__":
    unittest.main()
