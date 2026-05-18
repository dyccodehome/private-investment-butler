"""统一对外通讯网关。

所有用户可见输出都应该走 ``send(chat_id, text)``。
当前实现支持飞书 Webhook；本地 CLI 运行时会回退到标准输出。
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib import request, error

from src.app_config import get_config


_EXECUTOR = ThreadPoolExecutor(max_workers=4)


def send(chat_id: str, text: str) -> None:
    """非阻塞地把文本推送到已配置的聊天通道。"""

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
    """推送带动作按钮的飞书交互卡片。"""

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
    """异步 fire-and-forget 发送使用的尽力而为飞书 HTTP POST。"""

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
        # 通讯失败不能拖垮投资管道。
        return
