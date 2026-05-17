"""In-memory chat session lock and callback registry.

This is intentionally small. For multi-process deployment, replace these dicts
with Redis while keeping the same acquire/release API.
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
    """Try to mark a chat as busy. Return False if a pipeline is running."""

    with _LOCK:
        if chat_id in _PROCESSING_CHAT_IDS:
            return False
        _PROCESSING_CHAT_IDS.add(chat_id)
        return True


def release_processing(chat_id: str) -> None:
    """Clear the busy flag for a chat."""

    with _LOCK:
        _PROCESSING_CHAT_IDS.discard(chat_id)


def mark_event_seen(event_id: str) -> bool:
    """Return False for duplicate webhook deliveries."""

    if not event_id:
        return True
    with _LOCK:
        if event_id in _SEEN_EVENT_IDS:
            return False
        _SEEN_EVENT_IDS.add(event_id)
        return True


def save_pending_action(chat_id: str, action_id: str, reason: str, framework_id: str | None = None) -> None:
    """Store an action that requires Human-in-the-loop confirmation."""

    with _LOCK:
        _PENDING_ACTIONS[action_id] = PendingAction(
            chat_id=chat_id,
            action_id=action_id,
            framework_id=framework_id,
            reason=reason,
            created_at=time(),
        )


def pop_pending_action(action_id: str) -> PendingAction | None:
    """Resolve and remove a pending callback action."""

    with _LOCK:
        return _PENDING_ACTIONS.pop(action_id, None)
