"""带接单预检和两阶段推理的策略孤岛子 Agent 执行器。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.data_quality import summarize_disclosures
from src.init import FRAMEWORKS_DIR
from src.llm_client import LLMClient
from src.prompts import worker_system_prompt, worker_user_prompt
from src.research_dossier import extract_symbol, should_use_research_dossier
from src.symbol_ownership import symbol_in_framework
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
    "买入",
    "加仓",
    "补仓",
    "建仓",
    "减仓",
    "卖出",
    "仓位",
    "满仓",
    "执行建议",
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
    symbol = extract_symbol(state.user_input)
    if keywords and not any(keyword in text for keyword in keywords) and not symbol_in_framework(symbol, state.framework_id):
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
                    skill_name="market-data",
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
    """只把压缩后的披露事实传给模型提示词。"""

    disclosures = []
    for item in state.disclosed_data:
        disclosures.append(
            {
                "skill_name": item.skill_name,
                "arguments": item.arguments,
                "result": _compact_skill_payload(item.skill_name, item.payload),
            }
        )
    return json.dumps(
        {
            "data_quality_summary": summarize_disclosures(state.disclosed_data),
            "disclosures": disclosures,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _compact_skill_payload(skill_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Convert a loaded Skill payload into a bounded prompt-facing summary."""

    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    if not result:
        return {
            "payload_keys": sorted(payload.keys()),
            "payload_preview": _compact_text(str(payload), 800),
        }

    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    return {
        "status": result.get("status"),
        "source": result.get("source"),
        "data_type": result.get("data_type"),
        "freshness": result.get("freshness"),
        "warnings": result.get("warnings") or [],
        "error": _compact_text(str(result.get("error") or ""), 300),
        "data_quality": _compact_data_quality(result.get("data_quality")),
        "facts": _compact_skill_data(skill_name, data),
    }


def _compact_skill_data(skill_name: str, data: dict[str, Any]) -> dict[str, Any]:
    if skill_name == "portfolio_snapshot":
        return _compact_portfolio_snapshot(data)
    if skill_name in {"news-search", "announcement-search"}:
        return _compact_search_results(data)
    if skill_name == "trade_history":
        return {
            "symbol": data.get("symbol"),
            "framework_id": data.get("framework_id"),
            "match_count": data.get("match_count"),
            "matches": _limit_dict_list(data.get("matches"), 5),
        }
    if skill_name == "research_dossier":
        return _truncate_nested(data, max_string=500, max_items=8)
    if skill_name == "market-data":
        payload = data.get("payload") if isinstance(data.get("payload"), dict) else data
        return _compact_market_payload(payload)
    return _truncate_nested(data, max_string=500, max_items=8)


def _compact_portfolio_snapshot(data: dict[str, Any]) -> dict[str, Any]:
    dividend = data.get("dividend_analysis") if isinstance(data.get("dividend_analysis"), dict) else {}
    current_year = dividend.get("current_year_received") if isinstance(dividend.get("current_year_received"), dict) else {}
    forecast = dividend.get("forecast_from_holdings") if isinstance(dividend.get("forecast_from_holdings"), dict) else {}
    us_forecast = (
        dividend.get("us_income_distribution_forecast")
        if isinstance(dividend.get("us_income_distribution_forecast"), dict)
        else {}
    )
    yield_estimate = (
        dividend.get("portfolio_dividend_yield_estimate")
        if isinstance(dividend.get("portfolio_dividend_yield_estimate"), dict)
        else {}
    )
    return {
        "as_of": data.get("as_of"),
        "plan": _pick(data.get("plan"), "plan_name", "base_year", "retirement_years", "annual_contribution_target", "currency"),
        "summary": data.get("summary") if isinstance(data.get("summary"), dict) else {},
        "dividend_analysis": {
            "status": dividend.get("status"),
            "basis": dividend.get("basis"),
            "forecast_from_holdings": {
                "gross_annual_dividend_by_currency": forecast.get("gross_annual_dividend_by_currency"),
                "net_annual_dividend_by_currency": forecast.get("net_annual_dividend_by_currency"),
                "filled_position_count": forecast.get("filled_position_count"),
                "missing_position_count": forecast.get("missing_position_count"),
                "missing_annual_dividend_positions": _compact_identity_list(
                    forecast.get("missing_annual_dividend_positions")
                ),
            },
            "current_year_received": _pick(
                current_year,
                "year",
                "event_count",
                "total_by_currency",
                "plan_currency",
                "plan_currency_amount",
                "by_symbol",
            ),
            "us_income_distribution_forecast": {
                "policy": us_forecast.get("policy"),
                "position_count": len(us_forecast.get("positions") or []),
                "estimated_annual_cash_by_currency": us_forecast.get("estimated_annual_cash_by_currency"),
            },
            "portfolio_dividend_yield_estimate": _pick(
                yield_estimate,
                "policy",
                "by_market",
                "by_currency",
                "portfolio_total",
                "missing_positions",
            ),
            "answer_constraints": dividend.get("answer_constraints") or [],
            "repair_actions": dividend.get("repair_actions") or [],
        },
        "positions": [_compact_position(item) for item in _as_list(data.get("positions"))[:20]],
        "market_breakdown": data.get("market_breakdown") if isinstance(data.get("market_breakdown"), dict) else {},
        "position_limit_analysis": _compact_position_limit_analysis(data.get("position_limit_analysis")),
        "currency_breakdown": _pick(
            data.get("currency_breakdown"),
            "is_mixed_currency",
            "position_totals_by_currency",
            "dividend_events_by_currency",
        ),
        "market_data_summary": _compact_market_data_summary(data.get("market_data_summary")),
        "exchange_rates": _truncate_nested(data.get("exchange_rates"), max_string=240, max_items=10),
        "data_quality": data.get("data_quality") if isinstance(data.get("data_quality"), dict) else {},
        "market_data_policy": data.get("market_data_policy") if isinstance(data.get("market_data_policy"), dict) else {},
    }


def _compact_position(position: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": position.get("symbol"),
        "name": position.get("name"),
        "market": position.get("market"),
        "currency": position.get("currency"),
        "shares": position.get("shares"),
        "market_value": position.get("market_value"),
        "annual_dividend_per_share": position.get("annual_dividend_per_share"),
        "gross_annual_dividend": position.get("gross_annual_dividend"),
        "net_annual_dividend": position.get("net_annual_dividend"),
        "yield_on_cost": position.get("yield_on_cost"),
        "net_yield_on_cost": position.get("net_yield_on_cost"),
        "notes": _compact_text(str(position.get("notes") or ""), 160),
    }


def _compact_position_limit_analysis(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "status": value.get("status"),
        "scope": value.get("scope"),
        "denominator_market_value": value.get("denominator_market_value"),
        "policy": value.get("policy"),
        "positions": [
            _pick(
                item,
                "symbol",
                "name",
                "market_value",
                "weight",
                "limit_type",
                "limit_type_label",
                "limit_pct",
                "status",
                "can_add",
                "remaining_market_value_to_limit",
                "industry",
                "industry_label",
            )
            for item in _as_list(value.get("positions"))[:20]
        ],
        "industries": [
            _pick(
                item,
                "industry",
                "industry_label",
                "symbols",
                "market_value",
                "weight",
                "limit_pct",
                "status",
                "can_add",
                "remaining_market_value_to_limit",
            )
            for item in _as_list(value.get("industries"))[:12]
        ],
        "cyclical_total": _pick(
            value.get("cyclical_total"),
            "industries",
            "market_value",
            "weight",
            "limit_pct",
            "status",
            "can_add",
            "remaining_market_value_to_limit",
        ),
        "warnings": _compact_text_list(value.get("warnings"), limit=6, chars=180),
    }


def _compact_search_results(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "query": data.get("query"),
        "item_count": len(data.get("items") or []),
        "items": [
            {
                "title": _compact_text(str(item.get("title") or ""), 160),
                "summary": _compact_text(str(item.get("summary") or ""), 220),
                "source": item.get("source"),
                "published_at": item.get("published_at"),
                "url": item.get("url"),
                "cash_dividend_per_share": item.get("cash_dividend_per_share"),
            }
            for item in _as_list(data.get("items"))[:5]
        ],
    }


def _compact_market_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": payload.get("symbol") or payload.get("stock_code"),
        "market": payload.get("market"),
        "name": payload.get("name") or payload.get("stock_name"),
        "quote": _pick(payload.get("quote"), "price", "current", "change", "pct_change", "volume", "amount"),
        "technical": _pick(payload.get("technical"), "ma20", "ma60", "ma120", "trend"),
        "market_phase": payload.get("market_phase") if isinstance(payload.get("market_phase"), dict) else {},
        "data_quality": payload.get("data_quality") if isinstance(payload.get("data_quality"), dict) else {},
        "source_chain": payload.get("source_chain") if isinstance(payload.get("source_chain"), list) else [],
    }


def _compact_data_quality(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    pending_quote = _compact_identity_list(value.get("pending_quote_symbols"))
    missing_dividend = _compact_identity_list(value.get("missing_annual_dividend_symbols"))
    compact = {
        "status": value.get("status"),
        "coverage": value.get("coverage") if isinstance(value.get("coverage"), dict) else {},
        "freshness": value.get("freshness"),
        "limitations": _compact_text_list(value.get("limitations"), limit=6, chars=220),
        "warnings": _compact_text_list(value.get("warnings"), limit=6, chars=220),
        "pending_quote_count": len(pending_quote),
        "pending_quote_symbols": [item.get("symbol") for item in pending_quote if item.get("symbol")],
        "missing_annual_dividend_count": len(missing_dividend),
        "missing_annual_dividend_symbols": [
            item.get("symbol") for item in missing_dividend if item.get("symbol")
        ],
        "duplicate_symbol_groups": value.get("duplicate_symbol_groups") or [],
        "position_currencies": value.get("position_currencies") or [],
        "current_year_dividend_event_count": value.get("current_year_dividend_event_count"),
    }
    market_data = _compact_market_data_summary(value.get("market_data"))
    if market_data:
        compact["market_data"] = market_data
    return {key: item for key, item in compact.items() if item not in (None, "", [], {})}


def _compact_market_data_summary(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    error_symbols = []
    for item in _as_list(value.get("error_symbols"))[:20]:
        symbol = item.get("symbol")
        if symbol:
            error_symbols.append(symbol)
    return {
        "status_counts": value.get("status_counts") if isinstance(value.get("status_counts"), dict) else {},
        "error_symbols": error_symbols,
        "quote_missing_symbols": _as_text_list(value.get("quote_missing_symbols"), limit=20),
        "dividend_fields_ignored_symbols": _as_text_list(
            value.get("dividend_fields_ignored_symbols"),
            limit=20,
        ),
        "quote_dependent_metrics": _as_text_list(value.get("quote_dependent_metrics"), limit=8),
        "ledger_dependent_metrics": _as_text_list(value.get("ledger_dependent_metrics"), limit=8),
    }


def _pick(value: Any, *keys: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {key: value.get(key) for key in keys if key in value}


def _limit_dict_list(value: Any, limit: int) -> list[dict[str, Any]]:
    return [
        _truncate_nested(item, max_string=240, max_items=8)
        for item in _as_list(value)[:limit]
    ]


def _compact_identity_list(value: Any) -> list[dict[str, Any]]:
    return [
        _pick(item, "symbol", "name", "market", "currency", "shares")
        for item in _as_list(value)[:20]
    ]


def _compact_text_list(value: Any, *, limit: int, chars: int) -> list[str]:
    return [_compact_text(item, chars) for item in _as_text_list(value, limit=limit)]


def _as_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _as_text_list(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value[:limit] if str(item).strip()]


def _truncate_nested(value: Any, *, max_string: int, max_items: int) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _truncate_nested(child, max_string=max_string, max_items=max_items)
            for key, child in list(value.items())[:max_items]
        }
    if isinstance(value, list):
        return [_truncate_nested(item, max_string=max_string, max_items=max_items) for item in value[:max_items]]
    if isinstance(value, str):
        return _compact_text(value, max_string)
    return value


def _compact_text(text: str, limit: int) -> str:
    clean = " ".join(text.strip().split())
    if len(clean) <= limit:
        return clean
    return clean[:limit] + "...[truncated]"
