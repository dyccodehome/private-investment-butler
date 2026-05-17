"""Unified outbound communication gateway.

All user-visible output should go through ``send(chat_id, text)``. The current
implementation supports a Feishu incoming webhook and falls back to stdout for
local CLI runs.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib import request, error

from src.app_config import get_config


_EXECUTOR = ThreadPoolExecutor(max_workers=4)


def send(chat_id: str, text: str) -> None:
    """Push text to the configured chat channel without blocking the pipeline."""

    webhook_url = get_config().messaging().webhook_url
    if not webhook_url:
        print(f"[{chat_id}] {text}")
        return

    payload = {
        "msg_type": "text",
        "content": {"text": text},
    }
    _EXECUTOR.submit(_post_feishu, webhook_url, payload)


def send_card(chat_id: str, title: str, text: str, actions: list[dict[str, str]]) -> None:
    """Push an interactive Feishu card with action buttons."""

    webhook_url = get_config().messaging().webhook_url
    if not webhook_url:
        action_labels = " / ".join(action["label"] for action in actions)
        print(f"[{chat_id}] {title}\n{text}\nActions: {action_labels}")
        return

    payload = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": "red",
            },
            "elements": [
                {"tag": "markdown", "content": text},
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": action["label"]},
                            "type": action.get("type", "default"),
                            "value": {
                                "chat_id": chat_id,
                                "action": action["action"],
                                "state_id": action.get("state_id", ""),
                            },
                        }
                        for action in actions
                    ],
                },
            ],
        },
    }
    _EXECUTOR.submit(_post_feishu, webhook_url, payload)


def _post_feishu(webhook_url: str, payload: dict[str, Any]) -> None:
    """Best-effort Feishu HTTP POST used by async fire-and-forget sends."""

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        webhook_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        request.urlopen(req, timeout=5).read()
    except (error.URLError, TimeoutError):
        # Messaging must never crash the investment pipeline.
        return
