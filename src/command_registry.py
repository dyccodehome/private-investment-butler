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
        "contribute",
        "记录 Cash_Anchor 年度工资投入并返回完成进度",
        "Ledger",
        aliases=("salary", "deposit"),
        args_hint="<amount> [YYYY-MM-DD] [notes]",
    ),
    CommandDef(
        "plan",
        "修改 Cash_Anchor 年度工资投入目标",
        "Ledger",
        aliases=("target",),
        args_hint="contribution=<amount>",
    ),
    CommandDef(
        "holding",
        "新增或更新 Cash_Anchor 持仓并重算分红能力",
        "Ledger",
        aliases=("position",),
        args_hint="<symbol> <shares> <cost>",
    ),
    CommandDef(
        "holdings",
        "批量新增或更新 Cash_Anchor 持仓，每行一只股票",
        "Ledger",
        aliases=("positions",),
        args_hint="<multi-line records>",
    ),
    CommandDef(
        "buy",
        "记录买入事件并用加权成本更新持仓",
        "Ledger",
        args_hint="symbol=<code> shares=<n> price=<price> [date=YYYY-MM-DD]",
    ),
    CommandDef(
        "sell",
        "记录卖出事件并更新剩余持仓",
        "Ledger",
        args_hint="symbol=<code> shares=<n> price=<price> [date=YYYY-MM-DD]",
    ),
    CommandDef(
        "dividend",
        "记录现金分红到账事件",
        "Ledger",
        args_hint="symbol=<code> amount=<amount> [date=YYYY-MM-DD]",
    ),
    CommandDef("snapshot", "查看 Cash Anchor 本地持仓快照", "Ledger", aliases=("snap",)),
    CommandDef(
        "growth-holdings",
        "批量新增或更新 Growth_Engine 成长持仓，每行一只股票",
        "Growth",
        args_hint="<multi-line key=value records>",
    ),
    CommandDef("growth-snapshot", "查看 Growth_Engine 本地持仓和自选快照", "Growth", args_hint="[market=US|CN]"),
    CommandDef(
        "growth-watchlist",
        "批量新增或更新 Growth_Engine 自选股，每行一只股票",
        "Growth",
        args_hint="<multi-line key=value records>",
    ),
    CommandDef("growth-review", "按 Growth_Engine 框架复盘单个持仓或自选标的", "Growth", args_hint="<symbol>"),
    CommandDef("sync", "同步外部券商数据；当前支持 longbridge 占位检查", "Ledger", args_hint="longbridge"),
    CommandDef("apply", "确认并写入外部同步结果；当前支持 longbridge cash_anchor", "Ledger", args_hint="longbridge cash_anchor"),
    CommandDef(
        "absorb",
        "吸收外部知识并生成宪法补丁提案",
        "Knowledge",
        args_hint="<target_id> <文章链接、摘录或你的思考>",
    ),
]


def resolve_command(raw_text: str) -> tuple[CommandDef, str] | None:
    """解析用户输入的 slash command，返回命令定义和参数。"""

    text = raw_text.strip()
    if not text.startswith("/"):
        return None

    parts = text[1:].split(maxsplit=1)
    head = parts[0] if parts else ""
    args = parts[1] if len(parts) > 1 else ""
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
        "contribute": _handle_contribute,
        "plan": _handle_plan,
        "holding": _handle_holding,
        "holdings": _handle_holdings,
        "buy": _handle_buy,
        "sell": _handle_sell,
        "dividend": _handle_dividend,
        "snapshot": _handle_snapshot,
        "growth-holdings": _handle_growth_holdings,
        "growth-snapshot": _handle_growth_snapshot,
        "growth-watchlist": _handle_growth_watchlist,
        "growth-review": _handle_growth_review,
        "sync": _handle_sync,
        "apply": _handle_apply,
        "absorb": _handle_absorb,
    }
    handler = handlers.get(command.name)
    if not handler:
        return f"未知命令：/{command.name}"
    return handler(args, chat_id)


def help_text() -> str:
    """生成面向飞书/CLI 的命令帮助文案。"""

    lines = [
        "可用命令：",
        "",
        "信息：",
        "/help - 查看本帮助",
        "/status - 查看当前运行状态",
        "/usage - 查看今日模型 Token 用量",
        "/frameworks - 查看策略框架",
        "",
        "Cash Anchor 账本：",
        "/contribute <amount> [YYYY-MM-DD] [notes] - 记录年度工资投入",
        "/plan contribution=<amount> - 修改年度工资投入目标",
        "/holding <股票代码> <股数> <成本价> - 新增或更新单只红利持仓",
        "/holdings 后接多行：<股票代码> <股数> <成本价> - 批量新增或更新红利持仓",
        "/buy symbol=<code> shares=<n> price=<price> [date=YYYY-MM-DD] - 记录买入事件",
        "/sell symbol=<code> shares=<n> price=<price> [date=YYYY-MM-DD] - 记录卖出事件",
        "/dividend symbol=<code> amount=<amount> [date=YYYY-MM-DD] - 记录现金分红",
        "/snapshot - 查看 Cash Anchor 本地持仓快照",
        "/sync longbridge - 读取长桥持仓并生成同步提案",
        "/apply longbridge cash_anchor - 确认后把长桥 QQQI/XQQI/TQQQ 写入 Cash Anchor 账本",
        "",
        "Growth Engine：",
        "/growth-holdings 后接多行持仓参数 - 批量新增或更新成长持仓",
        "/growth-watchlist 后接多行自选参数 - 批量新增或更新成长自选股",
        "/growth-snapshot [market=US|CN] - 查看成长持仓和自选快照",
        "/growth-review <symbol> - 按成长框架复盘单个持仓或自选标的",
        "",
        "知识吸收：",
        "/absorb <target_id> <文章链接、摘录或你的思考>",
        "",
        "可用 target_id：",
        "- Cash_Anchor：现金流总框架，共同逻辑、资金池边界、总现金流目标",
        "- Cash_Anchor/CN_Dividend_Income：A 股红利子框架，境内红利、股息、MA120、分红税",
        "- Cash_Anchor/US_Income_Options：美股美元收益子框架，QQQI、XQQI、TQQQ、美元分红、期权收益",
        "- Growth_Engine：成长股总框架，共同逻辑、估值、增长、风控边界",
        "- Growth_Engine/CN_Alpha_Growth：A 股成长子框架，本土阿尔法、产业升级、趋势纪律",
        "- Growth_Engine/US_Disruptive_Growth：美股成长子框架，全球创新、AI、SaaS、TAM 与护城河",
        "",
        "示例：",
        "/absorb Cash_Anchor/CN_Dividend_Income 高股息不是安全边际，必须同时检查分红覆盖率和自由现金流。",
    ]
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
        f"- 待人工确认数：{status['pending_actions']}\n"
        f"- 进行中的补丁讨论数：{status['active_patch_discussions']}"
    )


def _handle_usage(args: str, chat_id: str) -> str:
    return f"今日本地记录的模型 Token 用量：{get_today_total_tokens()} tokens"


def _handle_frameworks(args: str, chat_id: str) -> str:
    return (
        "当前策略框架：\n"
        "- Cash_Anchor：现金流策略岛，含 A 股红利与美股收益期权子框架\n"
        "- Growth_Engine：成长股策略岛，含 A 股成长与美股成长子框架"
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


def _handle_contribute(args: str, chat_id: str) -> str:
    from datetime import date

    from src.portfolio_ledger import format_contribution_progress, record_capital_contribution

    parts = [part for part in args.strip().split() if not _is_feishu_mention_token(part)]
    if not parts:
        return "用法：/contribute <amount> [YYYY-MM-DD] [notes]\n示例：/contribute 5000 2026-05-24 A股红利池月度工资投入"

    try:
        amount = float(parts[0].replace(",", ""))
    except ValueError:
        return f"投入金额无法解析：{parts[0]}"

    contribution_date = date.today()
    note_start = 1
    if len(parts) >= 2:
        try:
            contribution_date = date.fromisoformat(parts[1])
            note_start = 2
        except ValueError:
            note_start = 1

    notes = " ".join(parts[note_start:]) or "A股红利池工资投入"
    try:
        result = record_capital_contribution(
            amount=amount,
            contribution_date=contribution_date,
            currency="CNY",
            source="salary",
            notes=notes,
        )
    except ValueError as exc:
        return str(exc)
    return format_contribution_progress(result)


def _handle_plan(args: str, chat_id: str) -> str:
    from src.portfolio_ledger import format_plan_progress, update_dividend_plan

    if not args.strip():
        return (
            "用法：/plan contribution=<amount>\n"
            "示例：/plan contribution=60000\n"
            "说明：系统不再设置目标年分红，年复盘时只评估实际分红、收益率和框架执行质量。"
        )

    parsed = _parse_key_values(args)
    allowed_keys = {"contribution", "annual_contribution"}
    unknown = sorted(set(parsed) - allowed_keys)
    if unknown:
        if any(item in {"dividend", "target_dividend"} for item in unknown):
            return "系统已取消目标年分红设置。请只使用 /plan contribution=<amount> 设置年度工资投入目标。"
        return f"未知目标字段：{', '.join(unknown)}。可用字段：contribution"

    contribution = _optional_amount(parsed.get("contribution") or parsed.get("annual_contribution"))
    if contribution is None:
        return "请提供年度工资投入目标：contribution=<amount>"

    try:
        snapshot = update_dividend_plan(
            annual_contribution_target=contribution,
        )
    except ValueError as exc:
        return str(exc)
    return format_plan_progress(snapshot)


def _handle_holding(args: str, chat_id: str) -> str:
    from src.portfolio_ledger import format_holding_progress, upsert_holding

    parsed = _parse_holding_args(args)
    required = ["symbol", "shares", "cost"]
    missing = [key for key in required if key not in parsed]
    if missing:
        return (
            "用法：/holding <股票代码> <股数> <成本价>\n"
            "示例：/holding 600900.SH 1000 24.5\n"
            "也支持：/holding symbol=600900.SH shares=1000 cost=24.5"
        )

    try:
        cost_price = _required_amount(parsed["cost"])
        current_price = _optional_amount(parsed.get("current")) or cost_price
        snapshot = upsert_holding(
            symbol=parsed["symbol"],
            name=parsed.get("name", ""),
            market=parsed.get("market", "A股"),
            currency=parsed.get("currency", "CNY"),
            shares=_required_amount(parsed["shares"]),
            cost_price=cost_price,
            current_price=current_price,
            annual_dividend_per_share=_optional_amount(parsed.get("dividend")) or 0.0,
            tax_rate=_optional_amount(parsed.get("tax")) or 0.0,
            notes=_append_pending_quote_note(parsed.get("notes", ""), has_current="current" in parsed),
        )
    except ValueError as exc:
        return str(exc)
    return format_holding_progress(snapshot)


def _handle_holdings(args: str, chat_id: str) -> str:
    from src.portfolio_ledger import upsert_holding

    rows = _parse_holding_batch_rows(args)
    if not rows:
        return (
            "用法：/holdings 后接多行持仓记录，每行一只股票。\n"
            "每行格式：<股票代码> <股数> <成本价>\n"
            "示例：\n"
            "/holdings\n"
            "600900.SH 1000 24.5\n"
            "601088.SH 500 31.2"
        )

    results: list[str] = []
    failures: list[str] = []
    required = ["symbol", "shares", "cost"]
    for index, row in enumerate(rows, start=1):
        missing = [key for key in required if key not in row]
        if missing:
            failures.append(f"第 {index} 行缺少字段：{', '.join(missing)}")
            continue
        try:
            cost_price = _required_amount(row["cost"])
            current_price = _optional_amount(row.get("current")) or cost_price
            snapshot = upsert_holding(
                symbol=row["symbol"],
                name=row.get("name", ""),
                market=row.get("market", "A股"),
                currency=row.get("currency", "CNY"),
                shares=_required_amount(row["shares"]),
                cost_price=cost_price,
                current_price=current_price,
                annual_dividend_per_share=_optional_amount(row.get("dividend")) or 0.0,
                tax_rate=_optional_amount(row.get("tax")) or 0.0,
                notes=_append_pending_quote_note(row.get("notes", ""), has_current="current" in row),
            )
        except ValueError as exc:
            failures.append(f"第 {index} 行失败：{exc}")
            continue
        holding = snapshot["updated_holding"]
        action = "更新" if snapshot["holding_action"] == "updated" else "新增"
        results.append(f"- {action}：{holding['symbol']} {holding['name']}，分红待估算")

    return _format_batch_result("红利持仓批量写入完成", results, failures)


def _handle_buy(args: str, chat_id: str) -> str:
    from datetime import date

    from src.portfolio_ledger import format_buy_progress, record_buy

    parsed = _parse_key_values(args)
    required = ["symbol", "shares", "price"]
    missing = [key for key in required if key not in parsed]
    if missing:
        return (
            "用法：/buy symbol=<code> shares=<n> price=<price> [date=YYYY-MM-DD] "
            "[name=<name>] [market=A股] [current=<price>] [dividend=<per_share>] [tax=0] [notes=<text>]\n"
            "示例：/buy symbol=600000 shares=1000 price=8.52 date=2026-05-25 name=示例银行 dividend=0.4"
        )

    try:
        snapshot = record_buy(
            symbol=parsed["symbol"],
            shares=_required_amount(parsed["shares"]),
            price=_required_amount(parsed["price"]),
            trade_date=date.fromisoformat(parsed["date"]) if parsed.get("date") else None,
            name=parsed.get("name", ""),
            market=parsed.get("market", "A股"),
            currency=parsed.get("currency", "CNY"),
            current_price=_optional_amount(parsed.get("current")),
            annual_dividend_per_share=_optional_amount(parsed.get("dividend")),
            tax_rate=_optional_amount(parsed.get("tax")),
            notes=parsed.get("notes", ""),
        )
    except ValueError as exc:
        return str(exc)
    return format_buy_progress(snapshot)


def _handle_sell(args: str, chat_id: str) -> str:
    from datetime import date

    from src.portfolio_ledger import format_sell_progress, record_sell

    parsed = _parse_key_values(args)
    required = ["symbol", "shares", "price"]
    missing = [key for key in required if key not in parsed]
    if missing:
        return (
            "用法：/sell symbol=<code> shares=<n> price=<price> [date=YYYY-MM-DD] [notes=<text>]\n"
            "示例：/sell symbol=600000 shares=500 price=9.10 date=2026-05-25"
        )

    try:
        snapshot = record_sell(
            symbol=parsed["symbol"],
            shares=_required_amount(parsed["shares"]),
            price=_required_amount(parsed["price"]),
            trade_date=date.fromisoformat(parsed["date"]) if parsed.get("date") else None,
            notes=parsed.get("notes", ""),
        )
    except ValueError as exc:
        return str(exc)
    return format_sell_progress(snapshot)


def _handle_dividend(args: str, chat_id: str) -> str:
    from datetime import date

    from src.portfolio_ledger import format_dividend_event, record_dividend

    parsed = _parse_key_values(args)
    required = ["symbol", "amount"]
    missing = [key for key in required if key not in parsed]
    if missing:
        return (
            "用法：/dividend symbol=<code> amount=<amount> [date=YYYY-MM-DD] [currency=CNY] [notes=<text>]\n"
            "示例：/dividend symbol=600000 amount=320.50 date=2026-06-20"
        )

    try:
        result = record_dividend(
            symbol=parsed["symbol"],
            amount=_required_amount(parsed["amount"]),
            dividend_date=date.fromisoformat(parsed["date"]) if parsed.get("date") else None,
            currency=parsed.get("currency", "CNY"),
            notes=parsed.get("notes", ""),
        )
    except ValueError as exc:
        return str(exc)
    return format_dividend_event(result)


def _handle_snapshot(args: str, chat_id: str) -> str:
    from src.portfolio_ledger import build_portfolio_snapshot, format_snapshot

    return format_snapshot(build_portfolio_snapshot())


def _handle_growth_holdings(args: str, chat_id: str) -> str:
    from src.growth_portfolio import upsert_growth_holding

    rows = _parse_batch_rows(args)
    if not rows:
        return (
            "用法：/growth-holdings 后接多行持仓记录，每行一只股票。\n"
            "每行格式：symbol=<code> shares=<n> cost=<price> current=<price> "
            "[name=<name>] [market=US|CN] [type=<核心仓|试错仓>] [thesis=<买入逻辑>]\n"
            "示例：\n"
            "/growth-holdings\n"
            "symbol=300750.SZ name=宁德时代 market=CN shares=100 cost=180 current=195 type=核心仓 thesis=动力电池龙头\n"
            "symbol=688256.SH name=寒武纪 market=CN shares=50 cost=600 current=650 type=试错仓 thesis=国产AI芯片"
        )

    results: list[str] = []
    failures: list[str] = []
    required = ["symbol", "shares", "cost", "current"]
    for index, row in enumerate(rows, start=1):
        missing = [key for key in required if key not in row]
        if missing:
            failures.append(f"第 {index} 行缺少字段：{', '.join(missing)}")
            continue
        try:
            snapshot = upsert_growth_holding(
                symbol=row["symbol"],
                name=row.get("name", ""),
                market=row.get("market", ""),
                sub_framework=row.get("sub_framework", ""),
                shares=_required_amount(row["shares"]),
                cost_price=_required_amount(row["cost"]),
                current_price=_required_amount(row["current"]),
                position_type=row.get("type") or row.get("position_type", "核心仓"),
                thesis=row.get("thesis", ""),
                status=row.get("status", "active"),
                last_review_at=row.get("last_review_at", ""),
                notes=row.get("notes", ""),
            )
        except ValueError as exc:
            failures.append(f"第 {index} 行失败：{exc}")
            continue
        holding = snapshot["updated_holding"]
        action = "更新" if snapshot["holding_action"] == "updated" else "新增"
        results.append(f"- {action}：{holding['symbol']} {holding['name']}")

    return _format_batch_result("成长持仓批量写入完成", results, failures)


def _handle_growth_snapshot(args: str, chat_id: str) -> str:
    from src.growth_portfolio import build_growth_snapshot, format_growth_snapshot

    parsed = _parse_key_values(args)
    market = parsed.get("market") or args.strip() or None
    return format_growth_snapshot(build_growth_snapshot(market=market))


def _handle_growth_watchlist(args: str, chat_id: str) -> str:
    from src.growth_portfolio import upsert_growth_watch_item

    rows = _parse_batch_rows(args)
    if not rows:
        return (
            "用法：/growth-watchlist 后接多行自选记录，每行一只股票。\n"
            "每行格式：symbol=<code> [name=<name>] [market=US|CN] "
            "[priority=high|medium|low] reason=<关注原因> trigger=<触发条件>\n"
            "示例：\n"
            "/growth-watchlist\n"
            "symbol=300750.SZ name=宁德时代 market=CN priority=high reason=新能源龙头 trigger=利润重新加速\n"
            "symbol=688981.SH name=中芯国际 market=CN priority=medium reason=国产半导体 trigger=毛利率企稳"
        )

    results: list[str] = []
    failures: list[str] = []
    for index, row in enumerate(rows, start=1):
        if "symbol" not in row:
            failures.append(f"第 {index} 行缺少字段：symbol")
            continue
        try:
            snapshot = upsert_growth_watch_item(
                symbol=row["symbol"],
                name=row.get("name", ""),
                market=row.get("market", ""),
                sub_framework=row.get("sub_framework", ""),
                priority=row.get("priority", "medium"),
                watch_reason=row.get("reason") or row.get("watch_reason", ""),
                trigger_condition=row.get("trigger") or row.get("trigger_condition", ""),
                status=row.get("status", "active"),
                last_review_at=row.get("last_review_at", ""),
                notes=row.get("notes", ""),
            )
        except ValueError as exc:
            failures.append(f"第 {index} 行失败：{exc}")
            continue
        item = snapshot["updated_watch_item"]
        action = "更新" if snapshot["watch_action"] == "updated" else "新增"
        results.append(f"- {action}：{item['symbol']} {item['name']}")

    return _format_batch_result("成长自选批量写入完成", results, failures)


def _handle_growth_review(args: str, chat_id: str) -> str:
    from src.growth_portfolio import review_growth_symbol

    symbol = args.strip().split()[0] if args.strip() else ""
    if not symbol:
        return "用法：/growth-review <symbol>\n示例：/growth-review NVDA.US"
    return review_growth_symbol(symbol, chat_id=chat_id)


def _handle_sync(args: str, chat_id: str) -> str:
    target = args.strip().lower()
    if target != "longbridge":
        return "用法：/sync longbridge\n当前仅规划长桥美股持仓同步。A 股持仓以本地账本和人工对账为准。"
    from src.longbridge_provider import format_longbridge_sync_proposal, sync_longbridge_positions

    try:
        proposal = sync_longbridge_positions()
    except RuntimeError as exc:
        return str(exc)
    return format_longbridge_sync_proposal(proposal)


def _handle_apply(args: str, chat_id: str) -> str:
    target = " ".join(args.strip().lower().split())
    if target != "longbridge cash_anchor":
        return "用法：/apply longbridge cash_anchor\n该命令会重新读取长桥持仓，只把 QQQI/XQQI/TQQQ 写入 Cash Anchor 账本。"
    from src.longbridge_provider import apply_longbridge_cash_anchor_sync, format_longbridge_apply_result

    try:
        result = apply_longbridge_cash_anchor_sync()
    except RuntimeError as exc:
        return str(exc)
    return format_longbridge_apply_result(result)


def _parse_key_values(args: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for part in args.strip().split():
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        result[key.strip().lower().replace("-", "_")] = value.strip()
    return result


def _parse_batch_rows(args: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in args.splitlines():
        clean = line.strip()
        if not clean or clean.startswith("#"):
            continue
        parsed = _parse_key_values(clean)
        if parsed:
            rows.append(parsed)
    return rows


def _parse_holding_args(args: str) -> dict[str, str]:
    clean_args = " ".join(part for part in args.strip().split() if not _is_feishu_mention_token(part))
    parsed = _parse_key_values(clean_args)
    if parsed:
        return parsed

    parts = clean_args.split()
    if len(parts) < 3:
        return {}

    result = {"symbol": parts[0]}
    if _looks_like_number(parts[1]):
        result["shares"] = parts[1]
        result["cost"] = parts[2]
        if len(parts) >= 4:
            result["current"] = parts[3]
    elif len(parts) >= 4:
        result["name"] = parts[1]
        result["shares"] = parts[2]
        result["cost"] = parts[3]
        if len(parts) >= 5:
            result["current"] = parts[4]
    return result


def _parse_holding_batch_rows(args: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in args.splitlines():
        clean = line.strip()
        if not clean or clean.startswith("#"):
            continue
        parsed = _parse_holding_args(clean)
        if parsed:
            rows.append(parsed)
    return rows


def _format_batch_result(title: str, results: list[str], failures: list[str]) -> str:
    lines = [f"{title}：成功 {len(results)} 条，失败 {len(failures)} 条"]
    if results:
        lines.extend(results)
    if failures:
        lines.append("")
        lines.append("失败明细：")
        lines.extend(f"- {item}" for item in failures)
    return "\n".join(lines)


def _append_pending_quote_note(notes: str, *, has_current: bool) -> str:
    clean = notes.strip()
    if has_current:
        return clean
    marker = "current_price=pending_quote"
    if marker in clean:
        return clean
    return f"{clean}; {marker}".strip("; ")


def _looks_like_number(value: str) -> bool:
    try:
        float(value.replace(",", ""))
    except ValueError:
        return False
    return True


def _is_feishu_mention_token(value: str) -> bool:
    return value.startswith("@_user_") or value.startswith("@ou_") or value.startswith("@oc_")


def _optional_amount(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    return float(value.replace(",", ""))


def _required_amount(value: str) -> float:
    return float(value.replace(",", ""))
