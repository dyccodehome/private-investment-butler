"""模型调用成本估算。

价格只从配置读取，不在代码里硬编码。没有配置价格时成本返回 0，保证本地开发可用。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from src.app_config import get_config
from src.init import RUNTIME_DIR


TOKEN_USAGE_DIR = RUNTIME_DIR / "token_usage"


def estimate_call_cost(
    *,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    reasoning_tokens: int = 0,
) -> float:
    """按每百万 token 单价估算一次调用成本。"""

    pricing = _model_pricing(provider, model)
    input_cost = input_tokens / 1_000_000 * float(pricing.get("input_per_1m") or 0)
    output_cost = output_tokens / 1_000_000 * float(pricing.get("output_per_1m") or 0)
    reasoning_cost = reasoning_tokens / 1_000_000 * float(pricing.get("reasoning_per_1m") or 0)
    return round(input_cost + output_cost + reasoning_cost, 6)


def daily_cost_summary(date: str | None = None) -> dict[str, Any]:
    """汇总指定日期的 token 和成本。"""

    target_date = date or datetime.now().strftime("%Y-%m-%d")
    path = TOKEN_USAGE_DIR / f"{target_date}.jsonl"
    summary: dict[str, Any] = {
        "date": target_date,
        "total_cost_usd": 0.0,
        "total_tokens": 0,
        "by_provider": {},
        "by_model": {},
        "records": 0,
    }
    if not path.exists():
        return summary

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        provider = str(record.get("provider") or "unknown")
        model = str(record.get("model") or "unknown")
        tokens = int(record.get("total_tokens") or 0)
        cost = float(record.get("estimated_cost_usd") or 0)
        summary["records"] += 1
        summary["total_tokens"] += tokens
        summary["total_cost_usd"] = round(float(summary["total_cost_usd"]) + cost, 6)
        _add_group(summary["by_provider"], provider, tokens, cost)
        _add_group(summary["by_model"], model, tokens, cost)
    return summary


def budget_warning(date: str | None = None) -> str | None:
    """当日成本达到阈值时返回提醒文案。"""

    settings = get_config().cost_management()
    budget = float(settings.get("daily_budget_usd") or 0)
    threshold = float(settings.get("warning_threshold") or 1)
    if budget <= 0:
        return None
    summary = daily_cost_summary(date)
    if float(summary["total_cost_usd"]) < budget * threshold:
        return None
    return (
        f"模型成本提醒：今日估算 ${summary['total_cost_usd']:.4f}，"
        f"已达到预算 ${budget:.2f} 的 {threshold:.0%} 阈值。"
    )


def _model_pricing(provider: str, model: str) -> dict[str, Any]:
    settings = get_config().cost_management()
    prices = settings.get("model_prices") or {}
    provider_prices = prices.get(provider) or {}
    return dict(provider_prices.get(model) or {})


def _add_group(group: dict[str, Any], key: str, tokens: int, cost: float) -> None:
    item = group.setdefault(key, {"total_tokens": 0, "total_cost_usd": 0.0, "records": 0})
    item["records"] += 1
    item["total_tokens"] += tokens
    item["total_cost_usd"] = round(float(item["total_cost_usd"]) + cost, 6)
