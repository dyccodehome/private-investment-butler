"""策略岛内的个股研究档案。

研究档案用于沉淀单个标的的长期判断：公司基本面、行业周期、买入理由、
看多逻辑、风险点、退出条件和后续事实变化。它不是静态笔记，而是给管道
持续检查“判断是否过期”的本地知识资产。
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from src.init import FRAMEWORKS_DIR
from src.state import AgentState


DEFAULT_STALE_AFTER_DAYS = 30
DOSSIER_DIR_NAME = "research_dossiers"
DOSSIER_FACT_TYPE_LABELS = {
    "financial_report": "财报候选",
    "profit_distribution": "利润分配候选",
    "equity_distribution_implementation": "权益分派实施候选",
    "risk_event": "风险事件候选",
    "business_update": "经营变化候选",
    "formal_disclosure": "正式披露候选",
    "news": "新闻线索候选",
}


@dataclass
class ResearchDossier:
    """单个标的的研究档案结构。"""

    symbol: str
    framework_id: str
    company_name: str = ""
    created_at: str = ""
    updated_at: str = ""
    last_fact_update_at: str = ""
    stale_after_days: int = DEFAULT_STALE_AFTER_DAYS
    status: str = "active"
    core_thesis: str = ""
    why_i_bought: list[str] = field(default_factory=list)
    bullish_case: list[str] = field(default_factory=list)
    bearish_case: list[str] = field(default_factory=list)
    fundamental_notes: list[str] = field(default_factory=list)
    industry_cycle: str = ""
    valuation_notes: str = ""
    quantitative_checks: list[dict[str, Any]] = field(default_factory=list)
    risk_points: list[str] = field(default_factory=list)
    exit_conditions: list[str] = field(default_factory=list)
    execution_rules: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    evidence_log: list[dict[str, Any]] = field(default_factory=list)
    decision_log: list[dict[str, Any]] = field(default_factory=list)


def build_research_dossier_snapshot(
    *,
    framework_id: str | None,
    symbol: str | None,
    user_query: str = "",
) -> dict[str, Any]:
    """读取或准备研究档案快照，供渐进披露注入模型。"""

    resolved_framework = framework_id or "unrouted"
    resolved_symbol = normalize_symbol(symbol or extract_symbol(user_query) or "UNKNOWN")
    dossier, path = load_or_create_dossier(resolved_framework, resolved_symbol)
    freshness = dossier_freshness(dossier)
    return {
        "framework_id": resolved_framework,
        "symbol": resolved_symbol,
        "path": str(path),
        "exists": path.exists(),
        "freshness": freshness,
        "dossier": asdict(dossier),
        "schema_version": 1,
        "principle": "资本市场里，过期的判断比没有判断更危险；研究档案必须跟随最新事实更新。",
    }


def load_or_create_dossier(framework_id: str, symbol: str) -> tuple[ResearchDossier, Path]:
    """读取档案；不存在时返回空档案对象但不主动写盘。"""

    path = dossier_path(framework_id, symbol)
    if not path.exists():
        now = _now()
        return (
            ResearchDossier(
                symbol=symbol,
                framework_id=framework_id,
                created_at=now,
                updated_at=now,
                last_fact_update_at="",
            ),
            path,
        )

    data = json.loads(path.read_text(encoding="utf-8"))
    return ResearchDossier(**_normalize_dossier_data(data, framework_id, symbol)), path


def save_dossier(dossier: ResearchDossier) -> Path:
    """把研究档案写回对应策略岛。"""

    path = dossier_path(dossier.framework_id, dossier.symbol)
    path.parent.mkdir(parents=True, exist_ok=True)
    dossier.updated_at = _now()
    path.write_text(json.dumps(asdict(dossier), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def append_decision_to_dossier(state: AgentState) -> Path | None:
    """在完整交互结束后，把本轮判断追加到相关个股档案。"""

    symbol = extract_symbol(state.user_input)
    if not state.framework_id or not symbol:
        return None
    if not should_use_research_dossier(state.user_input):
        return None

    dossier, _ = load_or_create_dossier(state.framework_id, normalize_symbol(symbol))
    dossier.decision_log.append(
        {
            "timestamp": _now(),
            "user_query": state.user_input,
            "context_bundle_id": state.context_bundle_id,
            "disclosed_skills": [item.skill_name for item in state.disclosed_data],
            "output_contract": state.output_contract,
            "decision_snapshot": state.decision_snapshot,
            "agent_proposal": state.draft_decision,
            "audit_signal": state.audit_signal,
            "final_reply": state.final_answer,
            "user_action": state.user_action,
            "status": state.status.value,
        }
    )
    return save_dossier(dossier)


def append_user_action_to_dossier(
    *,
    chat_id: str,
    framework_id: str | None,
    user_action: str,
    final_reply_to_user: str,
    reason: str = "",
) -> Path | None:
    """把飞书人工确认动作尽可能追加到对应个股档案。"""

    symbol = extract_symbol(" ".join([reason, final_reply_to_user]))
    if not framework_id or not symbol:
        return None

    normalized_symbol = normalize_symbol(symbol)
    dossier, _ = load_or_create_dossier(framework_id, normalized_symbol)
    now = _now()
    dossier.decision_log.append(
        {
            "timestamp": now,
            "user_query": "[interactive_callback]",
            "chat_id": chat_id,
            "context_bundle_id": "",
            "disclosed_skills": [],
            "output_contract": {},
            "decision_snapshot": {
                "version": 1,
                "created_at": now,
                "framework_id": framework_id,
                "symbol": normalized_symbol,
                "action_type": "human_override" if user_action == "user_clicked_force_execute" else "human_abandon",
                "audit_signal": "REJECT",
                "status": "human_action",
            },
            "agent_proposal": "",
            "audit_signal": "REJECT",
            "audit_reason": reason,
            "final_reply": final_reply_to_user,
            "user_action": user_action,
            "status": "human_action",
        }
    )
    return save_dossier(dossier)


def refresh_dossier_facts(
    *,
    framework_id: str,
    symbol: str,
    market: str | None = None,
    query: str | None = None,
    days: int = 120,
    limit: int = 10,
) -> dict[str, Any]:
    """用新闻、公告和正式披露刷新 dossier 事实证据。"""

    normalized_symbol = normalize_symbol(symbol)
    dossier, path = load_or_create_dossier(framework_id, normalized_symbol)
    existed_before_refresh = path.exists()
    clean_query = str(query or f"{normalized_symbol} 财报 分红 新闻 公告").strip()

    from src.market_intel import fetch_company_announcements, fetch_company_news, fetch_filings

    news = fetch_company_news(normalized_symbol, market=market, query=clean_query, limit=limit)
    announcements = fetch_company_announcements(
        normalized_symbol,
        market=market,
        query=clean_query,
        limit=limit,
        days=days,
    )
    filings = fetch_filings(
        normalized_symbol,
        market=market,
        query=clean_query,
        limit=limit,
        days=days,
    )
    sources = {
        "news": _compact_intel_payload(news),
        "announcement": _compact_intel_payload(announcements),
        "filing": _compact_intel_payload(filings),
    }
    item_counts = {key: len(value["items"]) for key, value in sources.items()}
    has_fact_items = any(count > 0 for count in item_counts.values())
    now = _now()
    refresh_record = {
        "timestamp": now,
        "source": "market_intel_refresh",
        "query": clean_query,
        "symbol": normalized_symbol,
        "market": str(market or ""),
        "days": days,
        "limit": limit,
        "status": "ok" if has_fact_items else "missing",
        "item_counts": item_counts,
        "sources": sources,
    }
    dossier.evidence_log.append(refresh_record)
    if has_fact_items:
        dossier.last_fact_update_at = now
    saved_path = save_dossier(dossier)
    return {
        "status": refresh_record["status"],
        "framework_id": framework_id,
        "symbol": normalized_symbol,
        "path": str(saved_path),
        "existed_before_refresh": existed_before_refresh,
        "last_fact_update_at": dossier.last_fact_update_at,
        "freshness": dossier_freshness(dossier),
        "item_counts": item_counts,
        "source_status": {key: value["status"] for key, value in sources.items()},
        "warnings": _refresh_warnings(sources),
    }


def format_dossier_refresh_result(result: dict[str, Any]) -> str:
    """把 dossier refresh 结果格式化给用户。"""

    lines = [
        "研究档案事实刷新完成：",
        f"- 标的：{result.get('symbol') or 'UNKNOWN'}",
        f"- 框架：{result.get('framework_id') or ''}",
        f"- 状态：{result.get('status') or 'unknown'}",
        f"- last_fact_update_at：{result.get('last_fact_update_at') or '未更新'}",
    ]
    counts = result.get("item_counts") if isinstance(result.get("item_counts"), dict) else {}
    if counts:
        lines.append(
            "- 命中条目："
            f"news={counts.get('news', 0)}, "
            f"announcement={counts.get('announcement', 0)}, "
            f"filing={counts.get('filing', 0)}"
        )
    warnings = [str(item) for item in result.get("warnings") or [] if str(item).strip()]
    if warnings:
        lines.append("- 缺口：" + "；".join(warnings[:3]))
    lines.append(f"- 文件：{result.get('path') or ''}")
    return "\n".join(lines)


def build_dossier_update_proposal(
    *,
    framework_id: str,
    symbol: str,
    market: str | None = None,
    query: str | None = None,
    days: int = 120,
    limit: int = 10,
) -> dict[str, Any]:
    """Generate a structured dossier update proposal without writing local state."""

    normalized_symbol = normalize_symbol(symbol)
    dossier, path = load_or_create_dossier(framework_id, normalized_symbol)
    clean_query = str(query or f"{normalized_symbol} 财报 分红 新闻 公告 风险").strip()

    from src.market_intel import fetch_company_announcements, fetch_company_news, fetch_filings

    raw_sources = {
        "news": fetch_company_news(normalized_symbol, market=market, query=clean_query, limit=limit),
        "announcement": fetch_company_announcements(
            normalized_symbol,
            market=market,
            query=clean_query,
            limit=limit,
            days=days,
        ),
        "filing": fetch_filings(
            normalized_symbol,
            market=market,
            query=clean_query,
            limit=limit,
            days=days,
        ),
    }
    sources = {
        source_type: _compact_intel_payload(payload, item_limit=limit)
        for source_type, payload in raw_sources.items()
    }
    candidate_facts = _build_dossier_candidate_facts(sources)
    item_counts = {key: len(value["items"]) for key, value in sources.items()}
    source_status = {key: value["status"] for key, value in sources.items()}
    return {
        "status": "ok" if candidate_facts else _proposal_status(source_status),
        "proposal_type": "research_dossier_update",
        "write_policy": "proposal_only_no_auto_write",
        "manual_review_required": True,
        "generated_at": _now(),
        "framework_id": framework_id,
        "symbol": normalized_symbol,
        "market": str(market or ""),
        "query": clean_query,
        "days": days,
        "limit": limit,
        "path": str(path),
        "existing_dossier": {
            "exists": path.exists(),
            "company_name": dossier.company_name,
            "last_fact_update_at": dossier.last_fact_update_at,
            "freshness": dossier_freshness(dossier),
        },
        "item_counts": item_counts,
        "source_status": source_status,
        "sources": sources,
        "candidate_facts": candidate_facts,
        "proposed_dossier_patch": _build_proposed_dossier_patch(candidate_facts),
        "warnings": _refresh_warnings(sources),
        "next_actions": [
            "人工打开候选事实的原始链接，核验标题、日期、正文和适用边界。",
            "只把已核验事实写入研究档案；新闻线索必须优先寻找正式公告或财报佐证。",
            "确认写入后再更新 last_fact_update_at，避免把未核验信息当作档案事实。",
        ],
    }


def format_dossier_update_proposal(proposal: dict[str, Any]) -> str:
    """Format a dossier update proposal for CLI or Feishu text output."""

    symbol = str(proposal.get("symbol") or "UNKNOWN")
    framework_id = str(proposal.get("framework_id") or "")
    existing = proposal.get("existing_dossier") if isinstance(proposal.get("existing_dossier"), dict) else {}
    freshness = existing.get("freshness") if isinstance(existing.get("freshness"), dict) else {}
    counts = proposal.get("item_counts") if isinstance(proposal.get("item_counts"), dict) else {}
    candidates = [item for item in proposal.get("candidate_facts") or [] if isinstance(item, dict)]
    lines = [
        "研究档案更新建议（未自动写入）：",
        f"- 标的：{symbol}",
        f"- 框架：{framework_id}",
        f"- 状态：{proposal.get('status') or 'unknown'}",
        f"- 档案事实状态：{freshness.get('reason') or '未读取到 freshness'}",
    ]
    if counts:
        lines.append(
            "- 来源命中："
            f"news={counts.get('news', 0)}, "
            f"announcement={counts.get('announcement', 0)}, "
            f"filing={counts.get('filing', 0)}"
        )

    if candidates:
        lines.append(f"候选事实 {len(candidates)} 条：")
        for item in candidates[:8]:
            evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
            title = str(evidence.get("title") or "").strip() or "未命名来源"
            published_at = str(evidence.get("published_at") or "").strip()
            label = str(item.get("fact_type_label") or item.get("fact_type") or "候选事实")
            target_sections = ", ".join(str(field) for field in item.get("target_sections") or [])
            date_prefix = f"{published_at} " if published_at else ""
            lines.append(f"- [{label}] {date_prefix}{title}；建议更新：{target_sections or 'evidence_log'}")
    else:
        lines.append("候选事实：本次没有足够来源生成更新建议。")

    warnings = [str(item) for item in proposal.get("warnings") or [] if str(item).strip()]
    if warnings:
        lines.append("缺口：" + "；".join(warnings[:3]))
    lines.append(f"文件：{proposal.get('path') or ''}")
    lines.append("下一步：人工核验原文后手动写入确认事实；本命令不会修改 dossier。")
    return "\n".join(lines)


def build_dossier_update_proposal_from_disclosures(disclosures: list[Any]) -> dict[str, Any] | None:
    """Build a dossier update proposal from Skill disclosures already gathered this turn."""

    context = _dossier_context_from_disclosures(disclosures)
    if not context:
        return None
    freshness = context.get("existing_dossier", {}).get("freshness")
    if isinstance(freshness, dict) and not freshness.get("is_stale"):
        return None
    sources = _intel_sources_from_disclosures(disclosures)
    if not any(payload.get("items") for payload in sources.values()):
        return None

    candidate_facts = _build_dossier_candidate_facts(sources)
    if not candidate_facts:
        return None
    source_status = {key: value["status"] for key, value in sources.items()}
    item_counts = {key: len(value["items"]) for key, value in sources.items()}
    return {
        "status": "ok",
        "proposal_type": "research_dossier_update",
        "write_policy": "proposal_only_no_auto_write",
        "manual_review_required": True,
        "generated_at": _now(),
        "framework_id": context["framework_id"],
        "symbol": context["symbol"],
        "market": context["market"],
        "query": context["query"],
        "days": 0,
        "limit": 0,
        "path": context["path"],
        "existing_dossier": context["existing_dossier"],
        "item_counts": item_counts,
        "source_status": source_status,
        "sources": sources,
        "candidate_facts": candidate_facts,
        "proposed_dossier_patch": _build_proposed_dossier_patch(candidate_facts),
        "warnings": _refresh_warnings(sources),
        "next_actions": [
            "人工核验本轮已披露的新闻和公告来源。",
            "确认后手动写入 dossier，并更新 last_fact_update_at。",
        ],
    }


def format_dossier_update_proposal_notice(proposal: dict[str, Any], *, max_items: int = 3) -> str:
    """Format a short final-answer notice for a disclosure-derived proposal."""

    candidates = [item for item in proposal.get("candidate_facts") or [] if isinstance(item, dict)]
    if not candidates:
        return ""
    lines = ["研究档案更新候选（未自动写入）："]
    for item in candidates[:max(1, max_items)]:
        evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
        title = str(evidence.get("title") or "").strip() or "未命名来源"
        label = str(item.get("fact_type_label") or item.get("fact_type") or "候选事实")
        lines.append(f"- [{label}] {title}")
    framework_id = str(proposal.get("framework_id") or "")
    symbol = str(proposal.get("symbol") or "")
    if framework_id and symbol:
        lines.append(f"完整复核：/review-dossier framework={framework_id} symbol={symbol}")
    lines.append("确认原文后再手动写入 dossier。")
    return "\n".join(lines)


def stale_dossier_notice_from_disclosures(disclosures: list[Any]) -> str:
    """从已披露 research_dossier 中生成面向最终回复的 stale 提示。"""

    for item in disclosures:
        if getattr(item, "skill_name", "") != "research_dossier":
            continue
        payload = getattr(item, "payload", {})
        if not isinstance(payload, dict):
            continue
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        freshness = result.get("freshness") if isinstance(result.get("freshness"), dict) else {}
        if not freshness:
            freshness = data.get("freshness") if isinstance(data.get("freshness"), dict) else {}
        if not freshness.get("is_stale"):
            continue
        symbol = str(data.get("symbol") or "").strip()
        framework_id = str(data.get("framework_id") or "").strip()
        reason = str(freshness.get("reason") or "研究档案可能过期，需要重新核对最新事实。")
        review_command = (
            f"/review-dossier framework={framework_id} symbol={symbol}"
            if framework_id and symbol
            else "/review-dossier framework=<Cash_Anchor|Growth_Engine> symbol=<symbol>"
        )
        return (
            f"研究档案提示：{symbol or '该标的'} 的历史判断可能过期。"
            f"{reason} 建议先执行 {review_command} 生成更新建议，人工确认后再改档案。"
        )
    return ""


def dossier_freshness(dossier: ResearchDossier) -> dict[str, Any]:
    """判断档案事实是否陈旧。"""

    if not dossier.last_fact_update_at:
        return {
            "is_stale": True,
            "days_since_fact_update": None,
            "stale_after_days": dossier.stale_after_days,
            "reason": "档案还没有事实更新时间。",
        }

    anchor = dossier.last_fact_update_at
    try:
        last_update = datetime.fromisoformat(anchor)
    except ValueError:
        return {
            "is_stale": True,
            "days_since_fact_update": None,
            "stale_after_days": dossier.stale_after_days,
            "reason": "档案时间格式无法解析。",
        }

    days = (datetime.now() - last_update).days
    is_stale = days > dossier.stale_after_days
    return {
        "is_stale": is_stale,
        "days_since_fact_update": days,
        "stale_after_days": dossier.stale_after_days,
        "reason": "判断可能过期，需要重新核对最新事实。" if is_stale else "档案仍在有效期内。",
    }


def should_use_research_dossier(user_input: str) -> bool:
    """判断本轮问题是否需要读取研究档案。"""

    text = user_input.lower()
    keywords = [
        "研究档案",
        "投研档案",
        "公司档案",
        "基本面",
        "行业周期",
        "为什么买",
        "买入理由",
        "看多",
        "风险点",
        "退出条件",
        "卖出条件",
        "财报",
        "论据",
        "逻辑记录",
        "复盘",
        "更新判断",
        "过期",
        "thesis",
        "dossier",
        "profile",
        "earnings",
    ]
    if any(keyword in text for keyword in keywords):
        return True
    return bool(extract_symbol(user_input))


def extract_symbol(text: str) -> str | None:
    """从用户输入里提取一个保守的标的代码。"""

    patterns = [
        r"(?<![A-Z0-9])\d{6}(?:\.(?:SH|SZ|SS))?(?![A-Z0-9])",
        r"(?<![A-Z0-9])(?:[A-Z]{2,5}(?:\.[A-Z]{1,3})?|[A-Z]\.[A-Z]{1,3})(?![A-Z0-9])",
    ]
    for pattern in patterns:
        match = re.search(pattern, text.upper())
        if match:
            return match.group(0)
    return None


def normalize_symbol(symbol: str) -> str:
    """把标的代码标准化为适合文件名的形式。"""

    clean = symbol.strip().upper().replace("/", "-")
    return re.sub(r"[^A-Z0-9._-]", "", clean) or "UNKNOWN"


def dossier_path(framework_id: str, symbol: str) -> Path:
    """返回标的研究档案路径。"""

    return FRAMEWORKS_DIR / framework_id / DOSSIER_DIR_NAME / f"{normalize_symbol(symbol)}.json"


def _normalize_dossier_data(data: dict[str, Any], framework_id: str, symbol: str) -> dict[str, Any]:
    base = asdict(ResearchDossier(symbol=symbol, framework_id=framework_id))
    base.update(data)
    base["symbol"] = normalize_symbol(str(base.get("symbol") or symbol))
    base["framework_id"] = str(base.get("framework_id") or framework_id)
    return base


def _dossier_context_from_disclosures(disclosures: list[Any]) -> dict[str, Any] | None:
    for disclosure in disclosures:
        if getattr(disclosure, "skill_name", "") != "research_dossier":
            continue
        result = _disclosure_result(disclosure)
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        framework_id = str(data.get("framework_id") or "").strip()
        symbol = str(data.get("symbol") or "").strip()
        if not framework_id or not symbol:
            continue
        freshness = data.get("freshness") if isinstance(data.get("freshness"), dict) else {}
        return {
            "framework_id": framework_id,
            "symbol": symbol,
            "market": "",
            "query": "",
            "path": str(data.get("path") or dossier_path(framework_id, symbol)),
            "existing_dossier": {
                "exists": bool(data.get("exists")),
                "company_name": str((data.get("dossier") or {}).get("company_name") or "")
                if isinstance(data.get("dossier"), dict)
                else "",
                "last_fact_update_at": str((data.get("dossier") or {}).get("last_fact_update_at") or "")
                if isinstance(data.get("dossier"), dict)
                else "",
                "freshness": freshness,
            },
        }
    return None


def _intel_sources_from_disclosures(disclosures: list[Any]) -> dict[str, dict[str, Any]]:
    sources = {
        "news": _empty_source_payload("news"),
        "announcement": _empty_source_payload("announcement"),
        "filing": _empty_source_payload("filing"),
    }
    for disclosure in disclosures:
        skill_name = str(getattr(disclosure, "skill_name", "") or "")
        source_type = {"news-search": "news", "announcement-search": "announcement"}.get(skill_name)
        if not source_type:
            continue
        result = _disclosure_result(disclosure)
        sources[source_type] = _compact_standard_intel_result(result, source_type=source_type)
    return sources


def _disclosure_result(disclosure: Any) -> dict[str, Any]:
    payload = getattr(disclosure, "payload", {})
    if not isinstance(payload, dict):
        return {}
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    return result if isinstance(result, dict) else {}


def _compact_standard_intel_result(result: dict[str, Any], *, source_type: str) -> dict[str, Any]:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    raw_items = data.get("items") if isinstance(data.get("items"), list) else []
    return {
        "status": str(result.get("status") or "missing"),
        "source": str(result.get("source") or ""),
        "data_type": str(result.get("data_type") or source_type),
        "error": str(result.get("error") or ""),
        "items": [_compact_intel_item(item) for item in raw_items[:10] if isinstance(item, dict)],
        "source_chain": [dict(item) for item in result.get("source_chain") or [] if isinstance(item, dict)],
    }


def _empty_source_payload(source_type: str) -> dict[str, Any]:
    return {
        "status": "missing",
        "source": "",
        "data_type": source_type,
        "error": "",
        "items": [],
        "source_chain": [],
    }


def _compact_intel_payload(payload: dict[str, Any], *, item_limit: int = 5) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    raw_items = data.get("items") if isinstance(data.get("items"), list) else []
    return {
        "status": str(payload.get("status") or "missing"),
        "source": str(payload.get("source") or ""),
        "data_type": str(payload.get("data_type") or ""),
        "error": str(payload.get("error") or ""),
        "items": [
            _compact_intel_item(item)
            for item in raw_items[: max(1, int(item_limit or 5))]
            if isinstance(item, dict)
        ],
        "source_chain": [dict(item) for item in payload.get("source_chain") or [] if isinstance(item, dict)],
    }


def _compact_intel_item(item: dict[str, Any]) -> dict[str, Any]:
    allowed = [
        "symbol",
        "name",
        "title",
        "summary",
        "category",
        "published_at",
        "report_date",
        "source",
        "provider",
        "url",
    ]
    result = {key: str(item.get(key) or "") for key in allowed if str(item.get(key) or "").strip()}
    if "summary" in result:
        result["summary"] = _truncate(result["summary"], 240)
    return result


def _build_dossier_candidate_facts(sources: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for source_type in ("filing", "announcement", "news"):
        payload = sources.get(source_type) or {}
        for item in payload.get("items") or []:
            if not isinstance(item, dict):
                continue
            candidate = _dossier_candidate_from_item(source_type, item, len(candidates) + 1)
            if candidate:
                candidates.append(candidate)
    return candidates


def _dossier_candidate_from_item(source_type: str, item: dict[str, Any], index: int) -> dict[str, Any]:
    fact_types = _classify_dossier_fact_types(source_type, item)
    primary_type = fact_types[0]
    label = DOSSIER_FACT_TYPE_LABELS.get(primary_type, primary_type)
    evidence = _candidate_evidence(source_type, item)
    target_sections = _target_sections_for_fact_types(fact_types)
    statement = _candidate_statement(label, evidence)
    return {
        "candidate_id": f"fact_{index:03d}",
        "source_type": source_type,
        "fact_type": primary_type,
        "fact_type_label": label,
        "fact_types": fact_types,
        "confidence": "high" if source_type in {"announcement", "filing"} else "medium",
        "statement": statement,
        "target_sections": target_sections,
        "evidence": evidence,
        "suggested_updates": _candidate_suggested_updates(
            target_sections=target_sections,
            evidence=evidence,
            fact_type=primary_type,
            statement=statement,
        ),
        "risk_implications": _risk_implications_for_fact_type(primary_type),
        "execution_discipline": _execution_discipline_for_fact_type(primary_type, source_type),
        "open_questions": _open_questions_for_fact_type(primary_type),
        "status": "pending_human_review",
    }


def _classify_dossier_fact_types(source_type: str, item: dict[str, Any]) -> list[str]:
    text = _candidate_text(item)
    checks = [
        (
            "equity_distribution_implementation",
            ["权益分派实施", "实施公告", "股权登记日", "除权除息", "现金红利发放日", "派息日"],
        ),
        (
            "profit_distribution",
            ["利润分配", "分红", "派息", "现金红利", "10派", "每10股派", "每股派"],
        ),
        (
            "financial_report",
            ["年度报告", "年报", "半年度报告", "半年报", "季度报告", "一季报", "三季报", "财务报告", "定期报告"],
        ),
        (
            "risk_event",
            ["风险", "减持", "诉讼", "处罚", "监管", "担保", "债务", "违约", "事故", "立案"],
        ),
        (
            "business_update",
            ["合同", "订单", "项目", "投产", "产能", "收购", "重组", "回购", "增持", "投资"],
        ),
    ]
    result = [fact_type for fact_type, tokens in checks if any(token in text for token in tokens)]
    if not result:
        result.append("news" if source_type == "news" else "formal_disclosure")
    if source_type == "news" and "news" not in result:
        result.append("news")
    return result


def _candidate_text(item: dict[str, Any]) -> str:
    return " ".join(
        str(item.get(key) or "")
        for key in ("title", "summary", "category", "source", "provider")
        if str(item.get(key) or "").strip()
    )


def _candidate_evidence(source_type: str, item: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_type": source_type,
        "symbol": str(item.get("symbol") or ""),
        "name": str(item.get("name") or ""),
        "title": str(item.get("title") or ""),
        "summary": str(item.get("summary") or ""),
        "category": str(item.get("category") or ""),
        "published_at": str(item.get("published_at") or ""),
        "report_date": str(item.get("report_date") or ""),
        "source": str(item.get("source") or ""),
        "provider": str(item.get("provider") or ""),
        "url": str(item.get("url") or ""),
    }


def _target_sections_for_fact_types(fact_types: list[str]) -> list[str]:
    mapping = {
        "financial_report": ["fundamental_notes", "quantitative_checks", "evidence_log"],
        "profit_distribution": ["fundamental_notes", "quantitative_checks", "evidence_log"],
        "equity_distribution_implementation": ["fundamental_notes", "execution_rules", "evidence_log"],
        "risk_event": ["risk_points", "exit_conditions", "open_questions", "evidence_log"],
        "business_update": ["fundamental_notes", "bullish_case", "bearish_case", "open_questions", "evidence_log"],
        "formal_disclosure": ["fundamental_notes", "open_questions", "evidence_log"],
        "news": ["open_questions", "evidence_log"],
    }
    result: list[str] = []
    for fact_type in fact_types:
        for section in mapping.get(fact_type, ["evidence_log"]):
            if section not in result:
                result.append(section)
    return result


def _candidate_statement(label: str, evidence: dict[str, Any]) -> str:
    title = evidence.get("title") or "未命名来源"
    published_at = evidence.get("published_at") or "日期未知"
    source = evidence.get("source") or evidence.get("provider") or "来源未知"
    return f"{label}：{published_at} {source}《{title}》需要人工核验后再写入研究档案。"


def _candidate_suggested_updates(
    *,
    target_sections: list[str],
    evidence: dict[str, Any],
    fact_type: str,
    statement: str,
) -> list[dict[str, Any]]:
    updates: list[dict[str, Any]] = []
    for section in target_sections:
        if section == "evidence_log":
            value: Any = {
                "timestamp": _now(),
                "source": "dossier_update_proposal",
                "fact_type": fact_type,
                "title": evidence.get("title") or "",
                "published_at": evidence.get("published_at") or "",
                "url": evidence.get("url") or "",
                "status": "pending_human_review",
            }
        else:
            value = statement
        updates.append({"field": section, "operation": "append", "value": value})
    return updates


def _risk_implications_for_fact_type(fact_type: str) -> list[str]:
    mapping = {
        "financial_report": ["复核营收、净利润、经营现金流、自由现金流、负债率是否支持原判断。"],
        "profit_distribution": ["复核分红覆盖率、自由现金流覆盖能力和一次性高分红风险。"],
        "equity_distribution_implementation": ["核对实际派息金额、登记日、除息日和到账日，避免账本提前确认。"],
        "risk_event": ["检查是否触发既有风险点、退出条件或仓位降级规则。"],
        "business_update": ["确认经营变化是长期基本面改善，还是一次性事件或资本开支压力。"],
        "formal_disclosure": ["正式披露只能说明事实发生，仍需判断对 thesis、估值和风控的影响。"],
        "news": ["新闻只作为线索；涉及重大事项时必须寻找正式公告佐证。"],
    }
    return mapping.get(fact_type, ["需要人工判断该事实是否改变原投资论据。"])


def _execution_discipline_for_fact_type(fact_type: str, source_type: str) -> list[str]:
    if source_type == "news":
        return ["未获得正式公告或财报佐证前，不把新闻线索写成确认事实。"]
    if fact_type in {"profit_distribution", "equity_distribution_implementation"}:
        return ["更新分红能力或到账流水前，必须人工核验正式披露文件。"]
    if fact_type == "financial_report":
        return ["财报数据进入 quantitative_checks 后，才允许据此改变买入、持有或退出结论。"]
    return ["先写入可追溯证据，再更新论据、风险点或执行纪律。"]


def _open_questions_for_fact_type(fact_type: str) -> list[str]:
    mapping = {
        "financial_report": ["关键财务指标相对上一期和买入时假设是否改善或恶化？"],
        "profit_distribution": ["分红是否由经营现金流覆盖，还是依赖一次性收益、借款或存量现金？"],
        "equity_distribution_implementation": ["实际到账金额、税费和到账日期是否已与券商流水一致？"],
        "risk_event": ["该风险是否已经进入原 dossier 的退出条件，是否需要降级观察？"],
        "business_update": ["该经营变化是否足以改变核心 thesis，还是只影响短期情绪？"],
        "news": ["是否存在同一事件的正式公告、财报或监管文件？"],
    }
    return mapping.get(fact_type, ["该事实应写入哪个 dossier 字段，是否改变原判断？"])


def _build_proposed_dossier_patch(candidate_facts: list[dict[str, Any]]) -> dict[str, list[Any]]:
    patch: dict[str, list[Any]] = {}
    seen: set[str] = set()
    for candidate in candidate_facts:
        for update in candidate.get("suggested_updates") or []:
            if not isinstance(update, dict):
                continue
            field_name = str(update.get("field") or "")
            if not field_name:
                continue
            value = update.get("value")
            marker = f"{field_name}:{json.dumps(value, ensure_ascii=False, sort_keys=True)}"
            if marker in seen:
                continue
            seen.add(marker)
            patch.setdefault(field_name, []).append(value)
    return patch


def _proposal_status(source_status: dict[str, str]) -> str:
    statuses = set(source_status.values())
    if statuses and statuses <= {"provider_not_configured"}:
        return "provider_not_configured"
    if "error" in statuses:
        return "error"
    if "empty" in statuses:
        return "empty"
    return "missing"


def _truncate(value: str, limit: int) -> str:
    clean = str(value or "").strip()
    return clean if len(clean) <= limit else clean[:limit].rstrip() + "..."


def _refresh_warnings(sources: dict[str, dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    for data_type, payload in sources.items():
        if payload.get("items"):
            continue
        error = str(payload.get("error") or "").strip()
        status = str(payload.get("status") or "missing")
        warnings.append(f"{data_type}={status}" + (f": {error}" if error else ""))
    return warnings


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat()
