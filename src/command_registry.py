"""轻量 Slash Command 注册表。

这个模块借鉴 Hermes 的集中式命令定义：命令说明、别名、帮助文案和网关分发
都从同一份注册表派生，避免后续飞书、CLI 和文档各写一套命令列表。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from src.token_monitor import get_today_total_tokens


CommandHandler = Callable[[str, str], str]


@dataclass(frozen=True)
class CommandDef:
    """单个 slash command 的元数据。"""

    name: str
    description: str
    category: str
    aliases: tuple[str, ...] = ()
    args_hint: str = ""


COMMAND_REGISTRY: list[CommandDef] = [
    CommandDef("help", "查看可用命令", "Info", aliases=("h",)),
    CommandDef("status", "查看当前 Agent 运行状态", "Info"),
    CommandDef("usage", "查看今日模型 Token 用量", "Info"),
    CommandDef("frameworks", "查看当前启用的投资策略框架", "Info", aliases=("fw",)),
    CommandDef(
        "absorb",
        "吸收外部知识并生成宪法补丁提案",
        "Knowledge",
        args_hint="<framework_id> <文章链接、摘录或你的思考>",
    ),
]


def resolve_command(raw_text: str) -> tuple[CommandDef, str] | None:
    """解析用户输入的 slash command，返回命令定义和参数。"""

    text = raw_text.strip()
    if not text.startswith("/"):
        return None

    head, _, args = text[1:].partition(" ")
    command_name = head.strip().lower().replace("_", "-")
    for command in COMMAND_REGISTRY:
        names = (command.name, *command.aliases)
        if command_name in {name.lower().replace("_", "-") for name in names}:
            return command, args.strip()
    return None


def handle_command(raw_text: str, chat_id: str) -> str | None:
    """执行已注册命令；非命令返回 None。"""

    resolved = resolve_command(raw_text)
    if not resolved:
        return None

    command, args = resolved
    handlers: dict[str, CommandHandler] = {
        "help": _handle_help,
        "status": _handle_status,
        "usage": _handle_usage,
        "frameworks": _handle_frameworks,
        "absorb": _handle_absorb,
    }
    handler = handlers.get(command.name)
    if not handler:
        return f"未知命令：/{command.name}"
    return handler(args, chat_id)


def help_text() -> str:
    """生成面向飞书/CLI 的命令帮助文案。"""

    lines = ["可用命令："]
    for command in COMMAND_REGISTRY:
        alias_text = f" alias: {', '.join('/' + item for item in command.aliases)}" if command.aliases else ""
        args_text = f" {command.args_hint}" if command.args_hint else ""
        lines.append(f"/{command.name}{args_text} - {command.description}{alias_text}")
    return "\n".join(lines)


def _handle_help(args: str, chat_id: str) -> str:
    return help_text()


def _handle_status(args: str, chat_id: str) -> str:
    from src.session_lock import runtime_status

    status = runtime_status()
    return (
        "Agent 状态：\n"
        f"- 当前 chat_id：{chat_id}\n"
        f"- 正在处理的会话数：{status['processing_chats']}\n"
        f"- 已记录事件数：{status['seen_events']}\n"
        f"- 待人工裁决数：{status['pending_actions']}"
    )


def _handle_usage(args: str, chat_id: str) -> str:
    return f"今日本地记录的模型 Token 用量：{get_today_total_tokens()} tokens"


def _handle_frameworks(args: str, chat_id: str) -> str:
    return (
        "当前策略框架：\n"
        "- Cash_Anchor：现金流策略岛，含 A 股红利与美股收益期权子框架\n"
        "- CN_Alpha_Growth：A 股成长股策略岛\n"
        "- US_Disruptive_Growth：美股颠覆性成长策略岛"
    )


def _handle_absorb(args: str, chat_id: str) -> str:
    from src.knowledge_absorber import (
        format_patch_proposal_for_user,
        parse_absorb_args,
        run_knowledge_absorption,
    )

    framework_id, source_text = parse_absorb_args(args)
    proposal = run_knowledge_absorption(framework_id, source_text, chat_id=chat_id)
    return format_patch_proposal_for_user(proposal)
