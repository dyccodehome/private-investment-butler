"""Scheduler job implementations."""

from __future__ import annotations

from src.dividend_disclosure import review_cn_dividend_disclosures
from src.growth_portfolio import review_growth_daily
from src.longbridge_provider import format_longbridge_us_income_result, sync_longbridge_us_income_distributions
from src.scheduled_review import (
    run_scheduled_close_review,
    run_scheduled_premarket_review,
    run_scheduled_weekly_review,
)


SCHEDULED_REVIEW_JOB_SPECS = {
    "cash_anchor_cn_premarket_review": ("Cash_Anchor", "CN", "premarket"),
    "cash_anchor_cn_close_review": ("Cash_Anchor", "CN", "close"),
    "cash_anchor_us_premarket_review": ("Cash_Anchor", "US", "premarket"),
    "growth_us_premarket_review": ("Growth_Engine", "US", "premarket"),
    "cash_anchor_us_close_review": ("Cash_Anchor", "US", "close"),
    "growth_us_close_review": ("Growth_Engine", "US", "close"),
    "cash_anchor_weekly_review": ("Cash_Anchor", "ALL", "weekly"),
    "growth_weekly_review": ("Growth_Engine", "ALL", "weekly"),
}


def is_scheduled_review_job_type(job_type: str) -> bool:
    return job_type in SCHEDULED_REVIEW_JOB_SPECS


def run_scheduled_review_job(job_type: str, *, chat_id: str | None, dry_run: bool) -> str:
    framework_id, market, workflow_type = SCHEDULED_REVIEW_JOB_SPECS[job_type]
    if dry_run:
        return f"[试运行] {framework_id} {market} {workflow_type} 定时工作流已匹配，未调用模型和外部数据源。"
    if workflow_type == "premarket":
        return run_scheduled_premarket_review(framework_id, market, chat_id=chat_id)
    if workflow_type == "close":
        return run_scheduled_close_review(framework_id, market, chat_id=chat_id)
    if workflow_type == "weekly":
        return run_scheduled_weekly_review(framework_id, chat_id=chat_id)
    raise ValueError(f"未知定时工作流类型：{workflow_type}")


def run_growth_daily_review_job(market: str, *, chat_id: str | None, dry_run: bool) -> str:
    if dry_run:
        return f"[试运行] 成长引擎 {market} 每日复盘任务已匹配，未调用模型。"
    return review_growth_daily(market, chat_id=chat_id)


def run_growth_weekly_review_job(*, chat_id: str | None, dry_run: bool) -> str:
    if dry_run:
        return "[试运行] 成长引擎周复盘任务已匹配，未调用模型。"
    return run_scheduled_weekly_review("Growth_Engine", chat_id=chat_id)


def run_cash_anchor_cn_dividend_review_job(*, chat_id: str | None, dry_run: bool) -> str:
    if dry_run:
        return "[试运行] 现金锚点境内红利财报核验已匹配，未生成正式核验清单。"
    return review_cn_dividend_disclosures(chat_id=chat_id)


def run_cash_anchor_us_income_distribution_job(*, chat_id: str | None, dry_run: bool) -> str:
    if dry_run:
        return "[试运行] 现金锚点美元收益分配同步已匹配，未调用长桥。"
    result = sync_longbridge_us_income_distributions()
    return format_longbridge_us_income_result(result)
