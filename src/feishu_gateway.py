"""处理飞书事件与交互回调的 FastAPI 网关。"""

from __future__ import annotations

import json
from typing import Any

from fastapi import BackgroundTasks, FastAPI, Request

from main import run_pipeline
from src import communication_gate
from src.app_config import get_config
from src.context_logger import save_user_action
from src.session_lock import (
    acquire_processing,
    mark_event_seen,
    pop_pending_action,
    release_processing,
)


app = FastAPI(title="Private Investment Butler Feishu Gateway")


@app.post("/webhook/feishu")
async def receive_feishu_event(request: Request, background_tasks: BackgroundTasks) -> dict[str, Any]:
    """接收飞书消息，立即返回，并在后台运行 Agent。"""

    payload = await request.json()

    if not _verify_feishu_token(payload):
        return {"code": 0, "msg": "verification failed"}

    # 飞书 URL 校验 challenge。
    if "challenge" in payload:
        return {"challenge": payload["challenge"]}

    event_id = _extract_event_id(payload)
    if not mark_event_seen(event_id):
        return {"code": 0, "msg": "duplicate ignored"}

    chat_id = _extract_chat_id(payload)
    text = _extract_text(payload)
    if not chat_id or not text:
        return {"code": 0, "msg": "ignored unsupported event"}

    if not acquire_processing(chat_id):
        communication_gate.send(chat_id, "管家正在为您全力审计上一条决策，请勿频繁轰炸。")
        return {"code": 0, "msg": "busy"}

    communication_gate.send(chat_id, "📥 已收到指令，首席路由器正在匹配投资框架...")
    background_tasks.add_task(_run_agent_background, chat_id, text)
    return {"code": 0, "msg": "received"}


@app.post("/webhook/callback")
async def receive_feishu_callback(request: Request) -> dict[str, Any]:
    """接收飞书交互卡片按钮点击。"""

    payload = await request.json()
    if not _verify_feishu_token(payload):
        return {"code": 0, "msg": "verification failed"}

    value = _extract_callback_value(payload)
    chat_id = value.get("chat_id", "")
    action = value.get("action", "")
    state_id = value.get("state_id", "")

    pending = pop_pending_action(state_id)
    if not pending:
        if chat_id:
            communication_gate.send(chat_id, "该裁决已过期或已处理。")
        return {"code": 0, "msg": "no pending action"}

    if action == "force_execute":
        reply = "已记录：主人驳回风控官意见，选择强行执行。后续将把该行为写入审计归因日志。"
        communication_gate.send(
            pending.chat_id,
            reply,
        )
        save_user_action(
            chat_id=pending.chat_id,
            framework_id=pending.framework_id,
            user_action="user_clicked_force_execute",
            final_reply_to_user=reply,
            reason=pending.reason,
        )
    elif action == "abandon_operation":
        reply = "已记录：主人接受风控官意见，放弃本次操作。"
        communication_gate.send(pending.chat_id, reply)
        save_user_action(
            chat_id=pending.chat_id,
            framework_id=pending.framework_id,
            user_action="user_clicked_abandon_operation",
            final_reply_to_user=reply,
            reason=pending.reason,
        )
    else:
        communication_gate.send(pending.chat_id, f"未知裁决动作：{action}")

    return {"code": 0, "msg": "callback handled"}


def _run_agent_background(chat_id: str, text: str) -> None:
    """在释放飞书 HTTP 连接后运行耗时 Agent 管道。"""

    try:
        run_pipeline(text, chat_id=chat_id)
    finally:
        release_processing(chat_id)


def _extract_event_id(payload: dict[str, Any]) -> str:
    """提取稳定事件 ID，用于抑制重复投递。"""

    return (
        str(payload.get("event_id") or "")
        or str(payload.get("header", {}).get("event_id") or "")
        or str(payload.get("uuid") or "")
    )


def _verify_feishu_token(payload: dict[str, Any]) -> bool:
    """配置 FEISHU_VERIFICATION_TOKEN 时校验飞书 token。

    这是 webhook 边界上的最低成本校验路径。若后续启用加密事件，
    应先解密再调用此解析逻辑。
    """

    expected = get_config().messaging().verification_token
    if not expected:
        return True
    actual = str(payload.get("token") or payload.get("header", {}).get("token") or "")
    return actual == expected


def _extract_chat_id(payload: dict[str, Any]) -> str:
    """从常见事件结构中提取飞书 chat_id。"""

    event = payload.get("event", {})
    message = event.get("message", {})
    return str(message.get("chat_id") or event.get("open_chat_id") or "")


def _extract_text(payload: dict[str, Any]) -> str:
    """从飞书消息 content JSON 中提取纯文本。"""

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


def _extract_callback_value(payload: dict[str, Any]) -> dict[str, str]:
    """从飞书回调 payload 中提取卡片按钮 value。"""

    action = payload.get("action", {})
    value = action.get("value", {})
    if isinstance(value, dict):
        return {str(k): str(v) for k, v in value.items()}
    return {}
