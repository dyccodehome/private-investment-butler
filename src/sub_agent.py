"""带接单预检和两阶段推理的策略孤岛子 Agent 执行器。"""

from __future__ import annotations

from pathlib import Path

from src.init import FRAMEWORKS_DIR
from src.llm_client import LLMClient
from src.prompts import worker_system_prompt, worker_user_prompt
from src.research_dossier import extract_symbol, should_use_research_dossier
from src.state import AgentState, PipelineStatus, SkillRequest


FRAMEWORK_KEYWORDS = {
    "Cash_Anchor": ["现金流", "红利", "股息", "分红", "低估值", "银行", "煤炭", "公用事业", "期权", "option", "covered call", "put", "call", "iv", "权利金", "退休", "持仓", "投入", "工资", "进度"],
    "Growth_Engine": ["a股", "中国", "成长", "科技自立", "出海", "半导体", "新能源", "ma120", "产业升级", "本土", "美股", "us", "ai", "saas", "生物科技", "英伟达", "微软", "全球", "颠覆", "tam"],
}

CASH_ANCHOR_LEDGER_KEYWORDS = [
    "持仓",
    "成本",
    "成本价",
    "股息率",
    "分红",
    "红利",
    "退休",
    "工资",
    "投入",
    "追加",
    "本金",
    "进度",
    "年度目标",
    "现金流目标",
    "今年会分多少",
]

CASH_ANCHOR_CONTEXT_BUNDLES = {
    "CN_Dividend_Income": {
        "path": "sub_frameworks/CN_Dividend_Income.md",
        "keywords": ["a股", "A股", "红利", "股息", "分红", "低估值", "银行", "煤炭", "电力", "公用事业", "运营商", "股息率"],
    },
    "US_Income_Options": {
        "path": "sub_frameworks/US_Income_Options.md",
        "keywords": [
            "美股",
            "us",
            "美元",
            "期权",
            "option",
            "options",
            "covered call",
            "cash secured put",
            "premium",
            "iv",
            "put",
            "call",
            "权利金",
        ],
    },
}

GROWTH_ENGINE_CONTEXT_BUNDLES = {
    "CN_Alpha_Growth": {
        "path": "sub_frameworks/CN_Alpha_Growth.md",
        "keywords": ["a股", "A股", "中国", "科技自立", "出海", "半导体", "新能源", "ma120", "产业升级", "本土"],
    },
    "US_Disruptive_Growth": {
        "path": "sub_frameworks/US_Disruptive_Growth.md",
        "keywords": ["美股", "us", "ai", "saas", "生物科技", "英伟达", "微软", "全球", "颠覆", "disruptive", "tam"],
    },
}


def load_constitution(framework_id: str) -> str:
    """只加载当前被选中策略框架的宪法。

    这用于强制策略隔离：一个策略 Worker 在处理任务时不会读取其他策略的规则。
    """

    path = FRAMEWORKS_DIR / framework_id / "constitution.md"
    return Path(path).read_text(encoding="utf-8")


def load_strategy_context(state: AgentState) -> str:
    """按策略和子框架加载最小必要上下文。

    普通策略只加载自己的宪法；带子框架的策略会先加载总纲，
    再按用户问题选择一个市场子框架，避免一次性注入两套规则。
    """

    if not state.framework_id:
        return ""

    framework_dir = FRAMEWORKS_DIR / state.framework_id
    context_files = [framework_dir / "constitution.md"]
    state.context_bundle_id = state.framework_id

    if state.framework_id == "Cash_Anchor":
        bundle_id = select_cash_anchor_context_bundle(state.user_input)
        state.context_bundle_id = bundle_id or "Cash_Anchor_Core"
        if bundle_id:
            bundle = CASH_ANCHOR_CONTEXT_BUNDLES[bundle_id]
            context_files.append(framework_dir / str(bundle["path"]))
    elif state.framework_id == "Growth_Engine":
        bundle_id = select_growth_engine_context_bundle(state.user_input)
        state.context_bundle_id = bundle_id or "Growth_Engine_Core"
        if bundle_id:
            bundle = GROWTH_ENGINE_CONTEXT_BUNDLES[bundle_id]
            context_files.append(framework_dir / str(bundle["path"]))

    state.loaded_context_files = [str(path.relative_to(FRAMEWORKS_DIR.parent)) for path in context_files]
    return "\n\n---\n\n".join(_read_context_file(path) for path in context_files)


def select_cash_anchor_context_bundle(user_input: str) -> str | None:
    """为现金流策略选择单个子框架；无法判断时返回 None。"""

    text = user_input.lower()
    scores: dict[str, int] = {}
    for bundle_id, bundle in CASH_ANCHOR_CONTEXT_BUNDLES.items():
        keywords = bundle["keywords"]
        scores[bundle_id] = sum(1 for keyword in keywords if str(keyword).lower() in text)

    best_bundle, best_score = max(scores.items(), key=lambda item: item[1])
    if best_score <= 0:
        return None
    return best_bundle


def select_growth_engine_context_bundle(user_input: str) -> str | None:
    """为成长策略选择单个子框架；无法判断时返回 None。"""

    text = user_input.lower()
    scores: dict[str, int] = {}
    for bundle_id, bundle in GROWTH_ENGINE_CONTEXT_BUNDLES.items():
        keywords = bundle["keywords"]
        scores[bundle_id] = sum(1 for keyword in keywords if str(keyword).lower() in text)

    best_bundle, best_score = max(scores.items(), key=lambda item: item[1])
    if best_score <= 0:
        return None
    return best_bundle


def intake_precheck(state: AgentState) -> AgentState:
    """让被选中的子 Agent 判断自己是否应该接单。

    这是弹回机制的守门逻辑。Master 路由器可能分配错误，
    所以子 Agent 会在消耗 LLM 或数据抓取预算之前先做一次低成本本地检查。
    """

    if not state.framework_id:
        state.append_error("Cannot precheck without framework_id.")
        return state

    text = state.user_input.lower()
    keywords = FRAMEWORK_KEYWORDS.get(state.framework_id, [])
    if keywords and not any(keyword in text for keyword in keywords):
        # 拒绝接单，并把任务交还主管道重新路由。
        state.bounce_back = True
        state.bounce_reason = (
            f"{state.framework_id} 预检拒单：用户问题与本策略宪法边界不匹配。"
        )
        state.status = PipelineStatus.BOUNCED
        return state

    # 能加载策略上下文说明子 Agent 已接单，后续只在自己的策略空间内推理。
    strategy_context = load_strategy_context(state)
    bundle_note = f"，上下文包：{state.context_bundle_id}" if state.context_bundle_id else ""
    state.worker_notes.append(
        f"{state.framework_id} 接单{bundle_note}。已加载上下文 {len(strategy_context)} 字。"
    )
    return state


def stage_one_request_skills(state: AgentState) -> AgentState:
    """子 Agent 只读取宪法和用户输入，然后申请所需数据。

    这实现渐进披露：子 Agent 不会预先拿到行情、持仓或新闻数据；
    它必须显式申请下一步推理所需的最小数据集。
    """

    if state.disclosed_data:
        # 当前管道轮次已经披露过数据，不再重复申请。
        return state

    symbol = extract_symbol(state.user_input)
    requested_skills: list[SkillRequest] = []
    if _needs_cash_anchor_ledger(state):
        requested_skills.append(
            SkillRequest(
                skill_name="portfolio_snapshot",
                arguments={"scope": "cash_anchor_dividend_retirement"},
                reason="需要读取 Cash_Anchor 本地持仓、年度投入计划、实际分红能力和只读行情数据，进行确定性计算。",
            )
        )
    if should_use_research_dossier(state.user_input):
        requested_skills.append(
            SkillRequest(
                skill_name="research_dossier",
                arguments={
                    "framework_id": state.framework_id,
                    "symbol": symbol or "UNKNOWN",
                    "user_query": state.user_input,
                },
                reason="需要读取或准备该标的的研究档案，检查历史论据、退出条件和判断是否过期。",
            )
        )

    if symbol:
        requested_skills.extend(
            [
                SkillRequest(
                    skill_name="hithink-market-query",
                    arguments={"symbol": symbol},
                    reason="需要通过统一市场数据 Provider 获取只读行情事实。",
                ),
                SkillRequest(
                    skill_name="trade_history",
                    arguments={"framework_id": state.framework_id, "symbol": symbol},
                    reason="需要读取历史决策逻辑，避免重复犯错。",
                ),
                SkillRequest(
                    skill_name="news-search",
                    arguments={"query": _news_query(symbol, state.user_input)},
                    reason="需要读取近期新闻情报，避免只用行情和本地账本做判断。",
                ),
            ]
        )
        if _needs_announcement_intel(state.user_input):
            requested_skills.append(
                SkillRequest(
                    skill_name="announcement-search",
                    arguments={"query": _announcement_query(symbol, state.user_input)},
                    reason="问题涉及财报、分红、风险或交易动作，需要核对正式公告口径。",
                )
            )
    else:
        state.worker_notes.append("未识别到具体标的代码，跳过行情与交易历史 Skill，避免把自然语言误当作证券代码。")

    if not requested_skills:
        requested_skills.append(
            SkillRequest(
                skill_name="news-search",
                arguments={"query": state.user_input[:120]},
                reason="未识别到具体标的代码，使用新闻搜索获取最低限度的背景信息。",
            )
        )
    state.requested_skills = requested_skills
    # 通知主管道暂停子 Agent 推理，先满足数据申请。
    state.status = PipelineStatus.NEEDS_DISCLOSURE
    return state


def stage_two_decide(state: AgentState) -> AgentState:
    """子 Agent 结合已披露数据和宪法做 If-Then 推理。

    Worker LLM 只能看到当前策略宪法、用户问题和主管道披露的数据。
    其他策略岛仍然保持隐藏。
    """

    data_names = ", ".join(item.skill_name for item in state.disclosed_data) or "no data"
    strategy_context = load_strategy_context(state)
    client = LLMClient.for_framework(state.framework_id)
    state.draft_decision = client.complete(
        system_prompt=worker_system_prompt(),
        user_prompt=worker_user_prompt(
            framework_id=state.framework_id,
            context_bundle_id=state.context_bundle_id,
            loaded_context_files=state.loaded_context_files,
            strategy_context=strategy_context,
            user_input=state.user_input,
            disclosed_data_names=data_names,
            disclosed_data=_compact_disclosed_data_for_prompt(state),
        ),
        agent_role="worker",
        call_site="sub_agent.stage_two_decide",
        framework_id=state.framework_id,
        context_bundle_id=state.context_bundle_id,
        chat_id=state.chat_id,
        user_query=state.user_input,
        trace_id=state.trace_id,
    )
    state.worker_notes.append("子 Agent 完成第二阶段推演，等待审计。")
    state.status = PipelineStatus.RUNNING
    return state


def _needs_cash_anchor_ledger(state: AgentState) -> bool:
    """判断本轮 Cash_Anchor 是否需要披露本地现金流账本。"""

    if state.framework_id != "Cash_Anchor":
        return False
    text = state.user_input.lower()
    return any(keyword.lower() in text for keyword in CASH_ANCHOR_LEDGER_KEYWORDS)


def _needs_announcement_intel(user_input: str) -> bool:
    text = user_input.lower()
    keywords = [
        "公告",
        "财报",
        "年报",
        "季报",
        "分红",
        "股息",
        "利润分配",
        "权益分派",
        "风险",
        "买入",
        "卖出",
        "加仓",
        "减仓",
        "建仓",
        "补仓",
        "earnings",
        "dividend",
    ]
    return any(keyword in text for keyword in keywords)


def _news_query(symbol: str, user_input: str) -> str:
    return f"{symbol} {user_input[:80]} 最新 新闻"


def _announcement_query(symbol: str, user_input: str) -> str:
    return f"{symbol} {user_input[:80]} 财报 公告 分红 风险"


def _read_context_file(path: Path) -> str:
    """读取策略上下文文件，并在提示词中保留相对路径来源。"""

    relative_path = path.relative_to(FRAMEWORKS_DIR.parent)
    return f"# 来源：{relative_path}\n\n{path.read_text(encoding='utf-8')}"


def _compact_disclosed_data_for_prompt(state: AgentState) -> str:
    """只把压缩后的披露元数据传给模型提示词。"""

    compact = []
    for item in state.disclosed_data:
        compact.append(
            {
                "skill_name": item.skill_name,
                "arguments": item.arguments,
                "payload": item.payload,
            }
        )
    return str(compact)
