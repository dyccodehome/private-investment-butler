from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.scheduled_health import format_scheduled_health, summarize_scheduled_health


class ScheduledHealthTest(unittest.TestCase):
    def test_summarize_flags_failures_obsolete_jobs_and_report_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs_path = root / "runtime" / "scheduler" / "runs.jsonl"
            runs_path.parent.mkdir(parents=True)
            runs = [
                {
                    "run_key": "2026-06-16:growth_us_close_review",
                    "job": "growth_us_close_review",
                    "job_type": "growth_us_close_review",
                    "market": "US",
                    "status": "ok",
                    "dry_run": False,
                    "error": "",
                    "result_preview": "ok",
                    "created_at": "2026-06-16T05:20:00+08:00",
                },
                {
                    "run_key": "2026-06-10:growth_cn_close_review",
                    "job": "growth_cn_close_review",
                    "job_type": "growth_cn_close_review",
                    "market": "CN",
                    "status": "error",
                    "dry_run": False,
                    "error": "IncompleteRead(0 bytes read)",
                    "result_preview": "定时任务失败",
                    "created_at": "2026-06-10T16:30:00+08:00",
                },
            ]
            runs_path.write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in runs),
                encoding="utf-8",
            )

            frameworks_dir = root / "frameworks"
            daily_dir = frameworks_dir / "Growth_Engine" / "reports" / "daily_reviews"
            daily_dir.mkdir(parents=True)
            report = {
                "record_id": "scheduled_1",
                "created_at": "2026-06-16T20:50:46",
                "review_date": "2026-06-16",
                "framework_id": "Growth_Engine",
                "market": "US",
                "workflow_type": "premarket",
                "status": "skipped",
                "tracked_symbol_count": 0,
                "context": {
                    "data_gaps": [
                        "长桥 Growth US universe 读取失败：longbridge positions 执行失败",
                    ]
                },
                "result": "skipped",
            }
            (daily_dir / "2026-06-16.jsonl").write_text(
                json.dumps(report, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            summary = summarize_scheduled_health(
                runs_path=runs_path,
                frameworks_dir=frameworks_dir,
                current_job_names={"growth_us_close_review"},
            )

        self.assertEqual(summary["scheduler_runs"]["status_counts"]["error"], 1)
        self.assertEqual(summary["scheduler_runs"]["obsolete_job_names"], ["growth_cn_close_review"])
        self.assertEqual(len(summary["scheduler_runs"]["recent_failures"]), 1)
        self.assertEqual(summary["reports"]["status_counts"]["skipped"], 1)
        self.assertEqual(len(summary["reports"]["zero_tracked_records"]), 1)
        self.assertEqual(len(summary["reports"]["longbridge_gap_records"]), 1)
        self.assertEqual(len(summary["reports"]["records_missing_account_activity"]), 1)
        self.assertEqual(len(summary["reports"]["records_missing_longbridge_market_context"]), 1)
        self.assertEqual(len(summary["reports"]["records_missing_longbridge_fundamental_context"]), 1)
        self.assertEqual(len(summary["reports"]["records_missing_longbridge_event_context"]), 1)
        self.assertEqual(len(summary["reports"]["growth_records_missing_research_engine"]), 1)
        self.assertEqual(len(summary["reports"]["growth_records_missing_operation_framework"]), 1)
        self.assertTrue(any("长桥" in item for item in summary["findings"]))

    def test_format_scheduled_health_includes_actionable_sections(self) -> None:
        summary = {
            "generated_at": "2026-06-21T10:00:00",
            "scheduler_runs": {
                "total": 2,
                "status_counts": {"ok": 1, "error": 1},
                "obsolete_job_names": ["growth_cn_close_review"],
                "recent_failures": [
                    {
                        "created_at": "2026-06-10T16:30:00+08:00",
                        "job": "growth_cn_close_review",
                        "market": "CN",
                        "error": "IncompleteRead(0 bytes read)",
                    }
                ],
            },
            "reports": {
                "total": 1,
                "status_counts": {"skipped": 1},
                "zero_tracked_records": [
                    {
                        "review_date": "2026-06-16",
                        "framework_id": "Growth_Engine",
                        "market": "US",
                        "workflow_type": "premarket",
                        "primary_gap": "长桥 Growth US universe 读取失败",
                    }
                ],
                "longbridge_gap_records": [{}],
                "records_missing_account_activity": [{}],
                "records_missing_longbridge_market_context": [{}],
                "records_missing_longbridge_fundamental_context": [{}],
                "records_missing_longbridge_event_context": [{}],
                "growth_records_missing_research_engine": [{}],
                "growth_records_missing_operation_framework": [{}],
                "top_data_gaps": [{"gap": "长桥 Growth US universe 读取失败", "count": 1}],
            },
            "findings": ["最近有 1 条报告包含长桥数据缺口"],
        }

        text = format_scheduled_health(summary, limit=3)

        self.assertIn("定时任务健康检查", text)
        self.assertIn("当前配置外的历史任务：growth_cn_close_review", text)
        self.assertIn("最近失败任务", text)
        self.assertIn("空标的报告", text)
        self.assertIn("US/ALL 报告缺 account_activity：1", text)
        self.assertIn("US/ALL 报告缺 longbridge_market_context：1", text)
        self.assertIn("US/ALL 报告缺 longbridge_fundamental_context：1", text)
        self.assertIn("US/ALL 报告缺 longbridge_event_context：1", text)
        self.assertIn("长桥 Growth US universe", text)


if __name__ == "__main__":
    unittest.main()
