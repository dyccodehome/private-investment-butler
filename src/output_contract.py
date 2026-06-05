"""Deterministic output contract and decision snapshots."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.data_quality import summarize_disclosures
from src.research_dossier import extract_symbol, normalize_symbol


CONTRACT_VERSION = 1
SECTION_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "conclusion": ("结论", "判断", "建议", "可以", "不建议", "维持", "观察"),
    "facts": ("事实", "依据", "数据", "财报", "公告", "行情", "持仓", "历史"),
    "risk": ("风险", "限制", "缺口", "不确定", "回撤", "误差"),
    "next_action": ("下一步", "动作", "执行", "观察", "等待", "条件", "触发"),
}


def apply_output_contract(state: Any) -> Any:
    """Attach contract validation and a reviewable decision snapshot to state."""

    state.output_contract = validate_draft_decision(state.draft_decision or "")
    state.decision_snapshot = build_decision_snapshot(state)
    missing = state.output_contract.get("missing_sections") or []
    if missing:
        note = f"输出契约缺失字段：{', '.join(missing)}。审计与复盘需重点检查。"
        if note not in state.worker_notes:
            state.worker_notes.append(note)
    return state


def validate_draft_decision(text: str) -> dict[str, Any]:
    """Validate the minimum structure required for investment-facing output."""

    clean = str(text or "").strip()
    sections: dict[str, bool] = {}
    for key, terms in SECTION_REQUIREMENTS.items():
        sections[key] = any(term.lower() in clean.lower() for term in terms)
    missing = [key for key, present in sections.items() if not present]
    return {
        "version": CONTRACT_VERSION,
        "status": "ok" if not missing else "warn",
        "required_sections": sections,
        "missing_sections": missing,
        "required_order": ["conclusion", "facts", "risk", "next_action"],
        "guidance": "面向用户的判断必须包含结论、关键事实、风险或限制、下一步动作。",
    }


def build_decision_snapshot(state: Any) -> dict[str, Any]:
    """Build a compact snapshot for future review and backtesting."""

    symbol = extract_symbol(str(state.user_input or ""))
    normalized_symbol = normalize_symbol(symbol) if symbol else ""
    return {
        "version": CONTRACT_VERSION,
        "created_at": datetime.now().replace(microsecond=0).isoformat(),
        "trace_id": getattr(state, "trace_id", ""),
        "framework_id": getattr(state, "framework_id", None),
        "context_bundle_id": getattr(state, "context_bundle_id", None),
        "symbol": normalized_symbol,
        "action_type": infer_action_type(
            " ".join(
                str(item or "")
                for item in [
                    getattr(state, "user_input", ""),
                    getattr(state, "draft_decision", ""),
                    getattr(state, "final_answer", ""),
                ]
            )
        ),
        "disclosed_skills": [item.skill_name for item in getattr(state, "disclosed_data", [])],
        "output_contract": getattr(state, "output_contract", {}) or validate_draft_decision(
            getattr(state, "draft_decision", "") or ""
        ),
        "data_quality_summary": summarize_disclosures(list(getattr(state, "disclosed_data", []) or [])),
        "historical_judgment_snapshot": extract_historical_judgments(
            list(getattr(state, "disclosed_data", []) or [])
        ),
        "market_phase_snapshot": extract_market_phase(list(getattr(state, "disclosed_data", []) or [])),
        "audit_signal": getattr(state, "audit_signal", None),
        "status": getattr(getattr(state, "status", None), "value", str(getattr(state, "status", ""))),
    }


def infer_action_type(text: str) -> str:
    clean = str(text or "").lower()
    keyword_groups = [
        ("buy", ("买入", "建仓", "开仓", "buy")),
        ("add", ("加仓", "补仓", "增持", "add")),
        ("sell", ("卖出", "清仓", "止损", "sell")),
        ("reduce", ("减仓", "降低仓位", "reduce")),
        ("hold", ("持有", "继续拿", "hold")),
        ("watch", ("观察", "等待", "watch")),
    ]
    for action, keywords in keyword_groups:
        if any(keyword in clean for keyword in keywords):
            return action
    return "review"


def extract_historical_judgments(disclosures: list[Any]) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    for item in disclosures:
        if getattr(item, "skill_name", "") != "trade_history":
            continue
        result = _result_payload(item)
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        for match in data.get("matches") or []:
            if isinstance(match, dict):
                matches.append(
                    {
                        "source": match.get("source"),
                        "framework_id": match.get("framework_id"),
                        "timestamp": match.get("timestamp"),
                        "audit_signal": match.get("audit_signal"),
                        "status": match.get("status"),
                        "final_reply_preview": match.get("final_reply_preview"),
                    }
                )
    return {
        "match_count": len(matches),
        "latest_matches": matches[:5],
    }


def extract_market_phase(disclosures: list[Any]) -> dict[str, Any]:
    for item in disclosures:
        if getattr(item, "skill_name", "") not in {
            "hithink-market-query",
        }:
            continue
        result = _result_payload(item)
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        payload = data.get("payload") if isinstance(data.get("payload"), dict) else data
        phase = payload.get("market_phase") if isinstance(payload, dict) else None
        if isinstance(phase, dict):
            return phase
    return {}


def _result_payload(item: Any) -> dict[str, Any]:
    payload = getattr(item, "payload", {})
    if not isinstance(payload, dict):
        return {}
    result = payload.get("result")
    return result if isinstance(result, dict) else {}
