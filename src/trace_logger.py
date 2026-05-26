"""全链路 Trace 事件记录器。

该模块是本地优先的 Agent Flight Recorder。主管道、LLM 网关、审计和通讯边界只需要
追加结构化事件，不需要依赖数据库或外部可观测平台。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from src.init import RUNTIME_DIR


TRACE_DIR = RUNTIME_DIR / "traces"


@dataclass
class TraceTimer:
    """用于记录某个节点耗时的轻量计时器。"""

    event_type: str
    started_at: float = field(default_factory=perf_counter)
    span_id: str = field(default_factory=lambda: f"span_{uuid4().hex[:10]}")

    def latency_ms(self) -> int:
        """返回从创建到当前时刻的毫秒耗时。"""

        return int((perf_counter() - self.started_at) * 1000)


def start_span(event_type: str) -> TraceTimer:
    """创建一个用于后续 ``trace_event`` 的计时器。"""

    return TraceTimer(event_type=event_type)


def trace_event(
    *,
    trace_id: str | None,
    event_type: str,
    chat_id: str | None = None,
    framework_id: str | None = None,
    agent_role: str | None = None,
    status: str = "success",
    span_id: str | None = None,
    parent_span_id: str | None = None,
    latency_ms: int | None = None,
    input_preview: str | None = None,
    output_preview: str | None = None,
    token_usage: dict[str, Any] | None = None,
    risk_flags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    error: str = "",
) -> Path:
    """追加一条结构化 Trace 事件。

    字段保持扁平，方便前端页面、脚本和未来周报 Agent 直接读取 JSONL。
    """

    now = datetime.now()
    record = {
        "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
        "trace_id": trace_id or f"trace_{uuid4().hex[:12]}",
        "span_id": span_id or f"span_{uuid4().hex[:10]}",
        "parent_span_id": parent_span_id,
        "chat_id": chat_id,
        "framework_id": framework_id,
        "agent_role": agent_role,
        "event_type": event_type,
        "status": status,
        "latency_ms": latency_ms,
        "input_preview": _preview(input_preview),
        "output_preview": _preview(output_preview),
        "token_usage": token_usage or {},
        "risk_flags": risk_flags or [],
        "metadata": metadata or {},
        "error": error,
    }

    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    path = TRACE_DIR / f"{now:%Y-%m-%d}.jsonl"
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    return path


def trace_state_event(
    state: Any,
    event_type: str,
    *,
    agent_role: str | None = None,
    status: str = "success",
    timer: TraceTimer | None = None,
    input_preview: str | None = None,
    output_preview: str | None = None,
    risk_flags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    error: str = "",
) -> Path:
    """从 AgentState 提取公共字段并写入 Trace。"""

    return trace_event(
        trace_id=getattr(state, "trace_id", None),
        event_type=event_type,
        chat_id=getattr(state, "chat_id", None),
        framework_id=getattr(state, "framework_id", None),
        agent_role=agent_role,
        status=status,
        span_id=timer.span_id if timer else None,
        latency_ms=timer.latency_ms() if timer else None,
        input_preview=input_preview if input_preview is not None else getattr(state, "user_input", None),
        output_preview=output_preview,
        risk_flags=risk_flags,
        metadata=metadata,
        error=error,
    )


def _preview(text: str | None, limit: int = 500) -> str | None:
    if text is None:
        return None
    clean = " ".join(str(text).split())
    return clean[:limit]
