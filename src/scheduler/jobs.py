"""Scheduler job implementations."""

from __future__ import annotations

from src.growth_portfolio import review_growth_daily


def run_growth_daily_review_job(market: str, *, chat_id: str | None, dry_run: bool) -> str:
    if dry_run:
        return f"[dry-run] Growth_Engine {market} 每日复盘任务已匹配，未执行 LLM。"
    return review_growth_daily(market, chat_id=chat_id)


def run_growth_weekly_review_job(*, chat_id: str | None, dry_run: bool) -> str:
    if dry_run:
        return "[dry-run] Growth_Engine 周复盘任务已匹配，未执行 LLM。"
    cn = review_growth_daily("CN", chat_id=chat_id)
    us = review_growth_daily("US", chat_id=chat_id)
    return "Growth_Engine 周复盘：\n\nA 股：\n" + cn + "\n\n美股：\n" + us
