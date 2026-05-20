"""内存版聊天会话锁与回调注册表。

这里刻意保持轻量。多进程部署时可以替换为 Redis，同时保持相同的 acquire/release API。
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from time import time


@dataclass
class PendingAction:
    chat_id: str
    action_id: str
    framework_id: str | None
    reason: str
    created_at: float


_LOCK = Lock()
_PROCESSING_CHAT_IDS: set[str] = set()
_SEEN_EVENT_IDS: set[str] = set()
_PENDING_ACTIONS: dict[str, PendingAction] = {}


def acquire_processing(chat_id: str) -> bool:
    """尝试把某个 chat 标记为忙碌；若已有管道运行则返回 False。"""

    with _LOCK:
        if chat_id in _PROCESSING_CHAT_IDS:
            return False
        _PROCESSING_CHAT_IDS.add(chat_id)
        return True


def release_processing(chat_id: str) -> None:
    """清除某个 chat 的忙碌标记。"""

    with _LOCK:
        _PROCESSING_CHAT_IDS.discard(chat_id)


def mark_event_seen(event_id: str) -> bool:
    """对重复投递的 webhook 返回 False。"""

    if not event_id:
        return True
    with _LOCK:
        if event_id in _SEEN_EVENT_IDS:
            return False
        _SEEN_EVENT_IDS.add(event_id)
        return True


def save_pending_action(chat_id: str, action_id: str, reason: str, framework_id: str | None = None) -> None:
    """存储一个需要人工介入确认的动作。"""

    with _LOCK:
        _PENDING_ACTIONS[action_id] = PendingAction(
            chat_id=chat_id,
            action_id=action_id,
            framework_id=framework_id,
            reason=reason,
            created_at=time(),
        )


def pop_pending_action(action_id: str) -> PendingAction | None:
    """解析并移除一个待处理回调动作。"""

    with _LOCK:
        return _PENDING_ACTIONS.pop(action_id, None)


def runtime_status() -> dict[str, int]:
    """返回网关内存状态快照，供 /status 命令展示。"""

    with _LOCK:
        return {
            "processing_chats": len(_PROCESSING_CHAT_IDS),
            "seen_events": len(_SEEN_EVENT_IDS),
            "pending_actions": len(_PENDING_ACTIONS),
        }
