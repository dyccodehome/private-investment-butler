"""Token 用量监控与本地 JSONL 账本。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from src.app_config import get_config
from src.init import RUNTIME_DIR


TOKEN_USAGE_DIR = RUNTIME_DIR / "token_usage"


def record_token_usage(
    *,
    model: str,
    agent_role: str,
    call_site: str,
    framework_id: str | None,
    chat_id: str | None,
    user_query: str | None,
    system_prompt: str,
    user_prompt: str,
    response: dict[str, Any] | None,
    latency_ms: int,
    status: str,
    error: str = "",
    context_bundle_id: str | None = None,
) -> Path | None:
    """追加一条模型调用用量记录。

    OpenAI 返回的 usage 数据被视为事实来源。若不可用，token 字段默认为 0，
    但 prompt 指纹仍可用于归因分析。
    """

    settings = get_config().token_monitor()
    if settings.get("enabled") is False:
        return None

    now = datetime.now()
    TOKEN_USAGE_DIR.mkdir(parents=True, exist_ok=True)
    log_path = TOKEN_USAGE_DIR / f"{now:%Y-%m-%d}.jsonl"
    usage = _extract_usage(response or {})
    record = {
        "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
        "model": model,
        "agent_role": agent_role,
        "call_site": call_site,
        "framework_id": framework_id,
        "context_bundle_id": context_bundle_id,
        "chat_id": chat_id,
        "user_query": user_query,
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "reasoning_tokens": usage["reasoning_tokens"],
        "total_tokens": usage["total_tokens"],
        "latency_ms": latency_ms,
        "status": status,
        "error": error,
        "prompt_fingerprint": _prompt_fingerprint(system_prompt, user_prompt),
    }
    with log_path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")
    return log_path


def build_token_warning(chat_id: str | None = None) -> str | None:
    """当今日 Token 用量超过阈值时返回提醒文案。"""

    settings = get_config().token_monitor()
    if settings.get("enabled") is False:
        return None

    limit = int(settings.get("daily_total_token_limit") or 0)
    threshold = float(settings.get("warning_threshold") or 1)
    if limit <= 0:
        return None

    today_total = get_today_total_tokens()
    trigger = int(limit * threshold)
    if today_total < trigger:
        return None

    scope = f"chat_id={chat_id}，" if chat_id else ""
    return (
        f"⚠️ Token 用量提醒：{scope}今日累计 {today_total} tokens，"
        f"已达到每日预算 {limit} 的 {threshold:.0%} 阈值。"
    )


def get_today_total_tokens() -> int:
    """汇总今天本地账本中的总 Token 数。"""

    path = TOKEN_USAGE_DIR / f"{datetime.now():%Y-%m-%d}.jsonl"
    if not path.exists():
        return 0
    total = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            total += int(json.loads(line).get("total_tokens") or 0)
        except json.JSONDecodeError:
            continue
    return total


def _extract_usage(response: dict[str, Any]) -> dict[str, int]:
    """标准化 Responses API 的 usage 字段。"""

    usage = response.get("usage") or {}
    input_tokens = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
    output_details = usage.get("output_tokens_details") or {}
    reasoning_tokens = int(output_details.get("reasoning_tokens") or usage.get("reasoning_tokens") or 0)
    total_tokens = int(usage.get("total_tokens") or input_tokens + output_tokens)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
        "total_tokens": total_tokens,
    }


def _prompt_fingerprint(system_prompt: str, user_prompt: str) -> str:
    """对提示词内容做哈希，既能归因重复成本，又不存储原文。"""

    digest = hashlib.sha256()
    digest.update(system_prompt.encode("utf-8"))
    digest.update(b"\n---USER---\n")
    digest.update(user_prompt.encode("utf-8"))
    return digest.hexdigest()[:16]
