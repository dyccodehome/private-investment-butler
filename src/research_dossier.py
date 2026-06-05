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
        refresh_command = (
            f"/dossier-refresh framework={framework_id} symbol={symbol}"
            if framework_id and symbol
            else "/dossier-refresh framework=<Cash_Anchor|Growth_Engine> symbol=<symbol>"
        )
        return (
            f"研究档案提示：{symbol or '该标的'} 的历史判断可能过期。"
            f"{reason} 建议先执行 {refresh_command} 后再更新结论。"
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


def _compact_intel_payload(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    raw_items = data.get("items") if isinstance(data.get("items"), list) else []
    return {
        "status": str(payload.get("status") or "missing"),
        "source": str(payload.get("source") or ""),
        "data_type": str(payload.get("data_type") or ""),
        "error": str(payload.get("error") or ""),
        "items": [_compact_intel_item(item) for item in raw_items[:5] if isinstance(item, dict)],
        "source_chain": [dict(item) for item in payload.get("source_chain") or [] if isinstance(item, dict)],
    }


def _compact_intel_item(item: dict[str, Any]) -> dict[str, Any]:
    allowed = ["symbol", "name", "title", "category", "published_at", "report_date", "source", "provider", "url"]
    return {key: str(item.get(key) or "") for key in allowed if str(item.get(key) or "").strip()}


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
