"""处理飞书事件与交互回调的 FastAPI 网关。"""

from __future__ import annotations

import json
import base64
import hashlib
from typing import Any
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, Request

from main import run_pipeline
from src import communication_gate
from src.app_config import get_config
from src.command_registry import handle_command, help_text
from src.context_logger import save_user_action
from src.knowledge_absorber import (
    accept_patch_proposal,
    format_patch_proposal_for_user,
    mark_patch_proposal,
    parse_absorb_args,
    run_knowledge_absorption,
)
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

    raw_body = await request.body()
    payload = _load_feishu_payload(raw_body)

    # 飞书 URL 校验 challenge。
    if payload.get("type") == "url_verification" or "challenge" in payload:
        if not _verify_url_challenge_token(payload):
            return {"code": 0, "msg": "verification failed"}
        return {"challenge": payload["challenge"]}

    if not _verify_feishu_token(payload) or not _verify_feishu_signature(request, raw_body):
        return {"code": 0, "msg": "verification failed"}

    event_id = _extract_event_id(payload)
    if not mark_event_seen(event_id):
        return {"code": 0, "msg": "duplicate ignored"}

    chat_id = _extract_chat_id(payload)
    text = _extract_text(payload)
    if not chat_id or not text:
        return {"code": 0, "msg": "ignored unsupported event"}

    if text.strip().startswith("/absorb"):
        try:
            framework_id, source_text = parse_absorb_args(text.strip().removeprefix("/absorb").strip())
        except ValueError as exc:
            communication_gate.send(chat_id, str(exc))
            return {"code": 0, "msg": "absorb usage error"}
        communication_gate.send(
            chat_id,
            "📥 已收到新知识，正在启动‘宪法再造’漏斗。生成冲突报告后会推送审批卡片。",
        )
        background_tasks.add_task(_run_absorb_background, chat_id, framework_id, source_text)
        return {"code": 0, "msg": "absorb received"}

    command_reply = handle_command(text, chat_id)
    if command_reply is not None:
        communication_gate.send(chat_id, command_reply)
        return {"code": 0, "msg": "command handled"}
    if text.strip().startswith("/"):
        communication_gate.send(chat_id, "未知命令。可发送 /help 查看可用命令。\n\n" + help_text())
        return {"code": 0, "msg": "unknown command"}

    if not acquire_processing(chat_id):
        communication_gate.send(chat_id, "管家正在为您全力审计上一条决策，请勿频繁轰炸。")
        return {"code": 0, "msg": "busy"}

    communication_gate.send(chat_id, "📥 已收到指令，首席路由器正在匹配投资框架...")
    background_tasks.add_task(_run_agent_background, chat_id, text)
    return {"code": 0, "msg": "received"}


@app.post("/webhook/callback")
async def receive_feishu_callback(request: Request) -> dict[str, Any]:
    """接收飞书交互卡片按钮点击。"""

    raw_body = await request.body()
    payload = _load_feishu_payload(raw_body)
    if not _verify_feishu_token(payload) or not _verify_feishu_signature(request, raw_body):
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

    if action in {"accept_constitution_patch", "observe_constitution_patch", "reject_constitution_patch"}:
        _handle_patch_callback(action, pending.chat_id, pending.framework_id, pending.reason)
    elif action == "force_execute":
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


def _run_absorb_background(chat_id: str, framework_id: str, source_text: str) -> None:
    """后台运行宪法再造管道并推送审批卡片。"""

    proposal = run_knowledge_absorption(framework_id, source_text, chat_id=chat_id)
    text = format_patch_proposal_for_user(proposal)
    if proposal.status != "proposed":
        communication_gate.send(chat_id, text)
        return

    action_id = str(uuid4())
    save_pending_action(
        chat_id=chat_id,
        action_id=action_id,
        framework_id=framework_id,
        reason=proposal.patch_id,
    )
    communication_gate.send_card(
        chat_id,
        f"宪法进化提案 {proposal.patch_id}",
        text,
        [
            {"label": "同意并打入宪法", "action": "accept_constitution_patch", "type": "primary", "state_id": action_id},
            {"label": "进入观察池", "action": "observe_constitution_patch", "type": "default", "state_id": action_id},
            {"label": "拒绝修改", "action": "reject_constitution_patch", "type": "danger", "state_id": action_id},
        ],
    )


def _handle_patch_callback(action: str, chat_id: str, framework_id: str | None, patch_id: str) -> None:
    """处理宪法补丁审批按钮。"""

    if not framework_id:
        communication_gate.send(chat_id, "补丁审批失败：缺少 framework_id。")
        return
    try:
        if action == "accept_constitution_patch":
            archive_path = accept_patch_proposal(framework_id, patch_id)
            communication_gate.send(chat_id, f"已打入宪法并完成本地 Git commit：{patch_id}\n归档：{archive_path}")
        elif action == "observe_constitution_patch":
            archive_path = mark_patch_proposal(framework_id, patch_id, "observing")
            communication_gate.send(chat_id, f"已放入观察池：{patch_id}\n归档：{archive_path}")
        elif action == "reject_constitution_patch":
            archive_path = mark_patch_proposal(framework_id, patch_id, "rejected")
            communication_gate.send(chat_id, f"已拒绝该宪法补丁：{patch_id}\n归档：{archive_path}")
    except Exception as exc:
        communication_gate.send(chat_id, f"补丁审批执行失败：{exc}")


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


def _verify_url_challenge_token(payload: dict[str, Any]) -> bool:
    """校验 URL verification 事件里的 token。"""

    expected = get_config().messaging().verification_token
    if not expected:
        return True
    return str(payload.get("token") or "") == expected


def _verify_feishu_signature(request: Request, raw_body: bytes) -> bool:
    """按飞书官方 demo 校验 X-Lark-Signature。"""

    encrypt_key = get_config().messaging().encrypt_key
    if not encrypt_key:
        return True

    timestamp = request.headers.get("X-Lark-Request-Timestamp", "")
    nonce = request.headers.get("X-Lark-Request-Nonce", "")
    signature = request.headers.get("X-Lark-Signature", "")
    if not timestamp or not nonce or not signature:
        return False

    digest = hashlib.sha256()
    digest.update((timestamp + nonce + encrypt_key).encode("utf-8"))
    digest.update(raw_body)
    return digest.hexdigest() == signature


def _load_feishu_payload(raw_body: bytes) -> dict[str, Any]:
    """解析飞书回调 JSON；配置加密时解开 ``encrypt`` 数据。"""

    payload = json.loads(raw_body.decode("utf-8") or "{}")
    encrypt_data = payload.get("encrypt")
    if not encrypt_data:
        return payload

    encrypt_key = get_config().messaging().encrypt_key
    if not encrypt_key:
        raise ValueError("FEISHU_ENCRYPT_KEY is required for encrypted callback")
    return json.loads(_decrypt_feishu_payload(str(encrypt_data), encrypt_key))


def _extract_chat_id(payload: dict[str, Any]) -> str:
    """从常见事件结构中提取飞书 chat_id。"""

    event = payload.get("event", {})
    message = event.get("message", {})
    return str(message.get("chat_id") or event.get("open_chat_id") or event.get("chat_id") or "")


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

    action = payload.get("action") or payload.get("event", {}).get("action", {})
    value = action.get("value", {})
    if isinstance(value, dict):
        return {str(k): str(v) for k, v in value.items()}
    return {}


def _decrypt_feishu_payload(encrypt_data: str, encrypt_key: str) -> str:
    """解密飞书加密回调。

    逻辑来自官方 demo：sha256(encrypt_key) 作为 AES-CBC key，
    密文前 16 字节为 IV，尾部使用 PKCS#7 padding。
    """

    try:
        from Crypto.Cipher import AES  # type: ignore
    except ModuleNotFoundError as exc:
        raise RuntimeError("请安装 pycryptodome 以支持飞书加密回调") from exc

    encrypted_bytes = base64.b64decode(encrypt_data)
    key = hashlib.sha256(encrypt_key.encode("utf-8")).digest()
    iv = encrypted_bytes[: AES.block_size]
    cipher = AES.new(key, AES.MODE_CBC, iv)
    decrypted = cipher.decrypt(encrypted_bytes[AES.block_size :])
    padding = decrypted[-1]
    return decrypted[:-padding].decode("utf-8")
