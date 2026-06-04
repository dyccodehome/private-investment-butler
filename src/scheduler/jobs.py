"""Scheduler job implementations."""

from __future__ import annotations

from src.dividend_disclosure import review_cn_dividend_disclosures
from src.growth_portfolio import review_growth_daily
from src.longbridge_provider import format_longbridge_us_income_result, sync_longbridge_us_income_distributions


def run_growth_daily_review_job(market: str, *, chat_id: str | None, dry_run: bool) -> str:
    if dry_run:
        return f"[试运行] 成长引擎 {market} 每日复盘任务已匹配，未调用模型。"
    return review_growth_daily(market, chat_id=chat_id)


def run_growth_weekly_review_job(*, chat_id: str | None, dry_run: bool) -> str:
    if dry_run:
        return "[试运行] 成长引擎周复盘任务已匹配，未调用模型。"
    cn = review_growth_daily("CN", chat_id=chat_id)
    us = review_growth_daily("US", chat_id=chat_id)
    return "成长引擎周复盘：\n\nA 股：\n" + cn + "\n\n美股：\n" + us


def run_cash_anchor_cn_dividend_review_job(*, chat_id: str | None, dry_run: bool) -> str:
    if dry_run:
        return "[试运行] 现金锚点境内红利财报核验已匹配，未生成正式核验清单。"
    return review_cn_dividend_disclosures(chat_id=chat_id)


def run_cash_anchor_us_income_distribution_job(*, chat_id: str | None, dry_run: bool) -> str:
    if dry_run:
        return "[试运行] 现金锚点美元收益分配同步已匹配，未调用长桥。"
    result = sync_longbridge_us_income_distributions()
    return format_longbridge_us_income_result(result)
