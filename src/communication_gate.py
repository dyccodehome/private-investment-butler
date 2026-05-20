"""统一对外通讯网关。

所有用户可见输出都应该走 ``send(chat_id, text)``。
当前优先使用飞书应用 OpenAPI；未配置应用凭据时可回退到 Webhook 或本地 CLI 输出。
"""

from __future__ import annotations

import json
import ssl
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib import request, error

from src.app_config import MessagingSettings, get_config


_EXECUTOR = ThreadPoolExecutor(max_workers=4)
_TENANT_TOKEN = ""
_TENANT_TOKEN_EXPIRES_AT = 0.0
SYSTEM_CA_PATH = Path("/etc/ssl/cert.pem")


def send(chat_id: str, text: str) -> None:
    """非阻塞地把文本推送到已配置的聊天通道。"""

    if chat_id == "cli":
        print(f"[{chat_id}] {text}")
        return

    settings = get_config().messaging()
    if settings.app_id and settings.app_secret:
        payload = {
            "receive_id": chat_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
        }
        _EXECUTOR.submit(_post_feishu_openapi_message, settings, "chat_id", payload)
        return

    if not settings.webhook_url:
        print(f"[{chat_id}] {text}")
        return

    payload = {
        "msg_type": "text",
        "content": {"text": text},
    }
    _EXECUTOR.submit(_post_feishu_webhook, settings.webhook_url, payload)


def send_card(chat_id: str, title: str, text: str, actions: list[dict[str, str]]) -> None:
    """推送带动作按钮的飞书交互卡片。"""

    if chat_id == "cli":
        action_labels = " / ".join(action["label"] for action in actions)
        print(f"[{chat_id}] {title}\n{text}\nActions: {action_labels}")
        return

    settings = get_config().messaging()
    card = _build_interactive_card(chat_id, title, text, actions)

    if settings.app_id and settings.app_secret:
        payload = {
            "receive_id": chat_id,
            "msg_type": "interactive",
            "content": json.dumps(card, ensure_ascii=False),
        }
        _EXECUTOR.submit(_post_feishu_openapi_message, settings, "chat_id", payload)
        return

    if not settings.webhook_url:
        action_labels = " / ".join(action["label"] for action in actions)
        print(f"[{chat_id}] {title}\n{text}\nActions: {action_labels}")
        return

    payload = {
        "msg_type": "interactive",
        "card": card,
    }
    _EXECUTOR.submit(_post_feishu_webhook, settings.webhook_url, payload)


def _build_interactive_card(chat_id: str, title: str, text: str, actions: list[dict[str, str]]) -> dict[str, Any]:
    """构造飞书交互卡片 JSON。"""

    return {
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
    }


def _post_feishu_openapi_message(
    settings: MessagingSettings,
    receive_id_type: str,
    payload: dict[str, Any],
) -> None:
    """通过飞书应用 OpenAPI 发送消息。"""

    try:
        token = _get_tenant_access_token(settings)
        _post_json(
            f"{settings.lark_host}/open-apis/im/v1/messages?receive_id_type={receive_id_type}",
            payload,
            {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
    except Exception:
        # 通讯失败不能拖垮投资管道。
        return


def _get_tenant_access_token(settings: MessagingSettings) -> str:
    """获取并缓存 tenant_access_token。"""

    global _TENANT_TOKEN, _TENANT_TOKEN_EXPIRES_AT

    now = time.time()
    if _TENANT_TOKEN and now < _TENANT_TOKEN_EXPIRES_AT:
        return _TENANT_TOKEN

    response = _post_json(
        f"{settings.lark_host}/open-apis/auth/v3/tenant_access_token/internal",
        {"app_id": settings.app_id, "app_secret": settings.app_secret},
        {"Content-Type": "application/json"},
    )
    token = str(response.get("tenant_access_token") or "")
    if not token:
        raise RuntimeError(f"Feishu tenant token missing: {response}")

    expire = int(response.get("expire") or 7200)
    _TENANT_TOKEN = token
    _TENANT_TOKEN_EXPIRES_AT = now + max(expire - 300, 60)
    return token


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    """向飞书 OpenAPI POST JSON 并检查业务错误码。"""

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(url, data=body, headers=headers, method="POST")
    with request.urlopen(req, timeout=5, context=_ssl_context()) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if int(data.get("code") or 0) != 0:
        raise RuntimeError(f"Feishu API error: {data}")
    return data


def _post_feishu_webhook(webhook_url: str, payload: dict[str, Any]) -> None:
    """异步 fire-and-forget 发送使用的尽力而为飞书 Webhook HTTP POST。"""

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        webhook_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        request.urlopen(req, timeout=5, context=_ssl_context()).read()
    except (error.URLError, TimeoutError):
        # 通讯失败不能拖垮投资管道。
        return


def _ssl_context() -> ssl.SSLContext:
    """创建 HTTPS 校验证书上下文，兼容 macOS Python 证书路径。"""

    paths = ssl.get_default_verify_paths()
    if paths.cafile:
        return ssl.create_default_context()
    if SYSTEM_CA_PATH.exists():
        return ssl.create_default_context(cafile=str(SYSTEM_CA_PATH))
    return ssl.create_default_context()
