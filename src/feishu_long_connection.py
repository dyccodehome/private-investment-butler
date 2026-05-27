"""飞书长连接入口。

本入口用于本地优先部署：不需要公网回调地址，通过飞书 Python SDK 的 WebSocket
长连接接收消息事件和卡片按钮回调。
"""

from __future__ import annotations

import json
import time
from typing import Any

from src.app_config import get_config
from src.feishu_runtime import handle_feishu_card_callback, handle_feishu_text_message
from src.session_lock import mark_event_seen


def main() -> None:
    """启动飞书长连接客户端。"""

    try:
        import lark_oapi as lark  # type: ignore
        from lark_oapi.api.im.v1.model.p2_im_message_receive_v1 import (  # type: ignore
            P2ImMessageReceiveV1,
        )
        from lark_oapi.event.callback.model.p2_card_action_trigger import (  # type: ignore
            P2CardActionTrigger,
            P2CardActionTriggerResponse,
        )
        from lark_oapi.event.dispatcher_handler import EventDispatcherHandler  # type: ignore
    except ModuleNotFoundError as exc:
        raise RuntimeError("请先安装飞书 Python SDK：pip install lark-oapi") from exc

    settings = get_config().messaging()
    if not settings.app_id or not settings.app_secret:
        raise RuntimeError("请先在 .env 中配置 FEISHU_APP_ID 和 FEISHU_APP_SECRET。")

    def on_message(data: P2ImMessageReceiveV1) -> None:
        payload = _model_to_dict(data)
        event_id = _extract_event_id(payload)
        if not mark_event_seen(event_id):
            print(f"Feishu message event skipped as duplicate: event_id={event_id}", flush=True)
            return
        chat_id = _extract_chat_id(payload)
        text = _extract_text(payload)
        print(
            "Feishu message event received: "
            f"event_id={event_id or '-'} chat_id={chat_id or '-'} text={_preview(text)}",
            flush=True,
        )
        handle_feishu_text_message(chat_id, text, async_run=True)

    def on_card_action(data: P2CardActionTrigger) -> Any:
        payload = _model_to_dict(data)
        value = _extract_card_value(payload)
        print(f"Feishu card action received: value_keys={sorted(value.keys())}", flush=True)
        result = handle_feishu_card_callback(value)
        return P2CardActionTriggerResponse({"toast": {"type": "info", "content": result}})

    event_handler = (
        EventDispatcherHandler.builder(settings.encrypt_key, settings.verification_token)
        .register_p2_im_message_receive_v1(on_message)
        .register_p2_card_action_trigger(on_card_action)
        .build()
    )
    while True:
        client = lark.ws.Client(settings.app_id, settings.app_secret, event_handler=event_handler)
        print("Feishu long connection started.", flush=True)
        try:
            client.start()
        except KeyboardInterrupt:
            print("Feishu long connection stopped by user.", flush=True)
            raise
        except Exception as exc:
            print(f"Feishu long connection crashed: {exc}", flush=True)
        print("Feishu long connection exited; restarting in 5 seconds.", flush=True)
        time.sleep(5)


def _model_to_dict(data: Any) -> dict[str, Any]:
    """尽量把 SDK model 转成普通 dict，兼容不同 SDK 版本。"""

    if isinstance(data, dict):
        return data
    for method_name in ("to_dict", "model_dump", "dict"):
        method = getattr(data, method_name, None)
        if callable(method):
            result = method()
            if isinstance(result, dict):
                return result
    raw = getattr(data, "raw", None)
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    body = getattr(data, "body", None)
    if isinstance(body, dict):
        return body
    return json.loads(json.dumps(data, default=lambda obj: getattr(obj, "__dict__", str(obj))))


def _extract_event_id(payload: dict[str, Any]) -> str:
    return (
        str(payload.get("event_id") or "")
        or str(payload.get("header", {}).get("event_id") or "")
        or str(payload.get("uuid") or "")
    )


def _extract_chat_id(payload: dict[str, Any]) -> str:
    event = payload.get("event", {})
    message = event.get("message", {})
    return str(message.get("chat_id") or event.get("open_chat_id") or event.get("chat_id") or "")


def _extract_text(payload: dict[str, Any]) -> str:
    message = payload.get("event", {}).get("message", {})
    content = message.get("content", "")
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return content.strip()
        return str(parsed.get("text") or "").strip()
    if isinstance(content, dict):
        return str(content.get("text") or "").strip()
    return ""


def _extract_card_value(payload: dict[str, Any]) -> dict[str, Any]:
    action = payload.get("action") or payload.get("event", {}).get("action", {})
    value = action.get("value", {})
    if isinstance(value, dict):
        return value
    return {}


def _preview(text: str, limit: int = 80) -> str:
    text = text.replace("\n", "\\n")
    if len(text) <= limit:
        return repr(text)
    return repr(text[:limit] + "...")


if __name__ == "__main__":
    main()
