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

    trade_guardrail = build_trade_guardrail_contract(state)
    if trade_guardrail:
        state.draft_decision = _append_trade_guardrail_note(
            getattr(state, "draft_decision", "") or "",
            trade_guardrail,
        )
    state.output_contract = validate_draft_decision(state.draft_decision or "")
    if trade_guardrail:
        state.output_contract["trade_guardrail"] = trade_guardrail
        if trade_guardrail.get("status") != "ok":
            state.output_contract["status"] = "warn"
    state.decision_snapshot = build_decision_snapshot(state)
    missing = state.output_contract.get("missing_sections") or []
    if missing:
        note = f"输出契约缺失字段：{', '.join(missing)}。审计与复盘需重点检查。"
        if note not in state.worker_notes:
            state.worker_notes.append(note)
    if trade_guardrail and trade_guardrail.get("status") != "ok":
        note = f"交易仓位纪律：{trade_guardrail.get('summary') or trade_guardrail.get('status')}"
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
        "trade_guardrail": (getattr(state, "output_contract", {}) or {}).get("trade_guardrail", {}),
        "audit_signal": getattr(state, "audit_signal", None),
        "status": getattr(getattr(state, "status", None), "value", str(getattr(state, "status", ""))),
    }


def build_trade_guardrail_contract(state: Any) -> dict[str, Any]:
    """Build deterministic Cash Anchor add/buy guardrails from disclosed portfolio data."""

    if getattr(state, "framework_id", None) != "Cash_Anchor":
        return {}
    action = infer_action_type(str(getattr(state, "user_input", "") or ""))
    if action not in {"buy", "add"}:
        return {}
    symbol = extract_symbol(str(getattr(state, "user_input", "") or ""))
    if not symbol:
        return {
            "version": CONTRACT_VERSION,
            "status": "missing",
            "action_type": action,
            "symbol": "",
            "summary": "买入/加仓意图未识别到标的代码，不能计算严格加仓额度。",
            "issues": ["missing_symbol"],
        }

    analysis = _position_limit_analysis_from_disclosures(list(getattr(state, "disclosed_data", []) or []))
    if not analysis:
        return {
            "version": CONTRACT_VERSION,
            "status": "missing",
            "action_type": action,
            "symbol": normalize_symbol(symbol),
            "summary": "缺少 position_limit_analysis，不能计算严格加仓额度。",
            "issues": ["missing_position_limit_analysis"],
        }

    row = _find_position_limit_row(analysis, symbol)
    if not row:
        return {
            "version": CONTRACT_VERSION,
            "status": "missing",
            "action_type": action,
            "symbol": normalize_symbol(symbol),
            "scope": analysis.get("scope") or "A股红利池",
            "summary": "目标标的未出现在 A 股红利池持仓上限分析中，不能给出确定加仓额度。",
            "issues": ["target_symbol_not_in_position_limit_analysis"],
        }

    add_guardrail = row.get("add_guardrail") if isinstance(row.get("add_guardrail"), dict) else {}
    max_add = _to_float(add_guardrail.get("strict_max_add_market_value") or row.get("strict_max_add_market_value"))
    can_add = bool(add_guardrail.get("can_add") if "can_add" in add_guardrail else row.get("can_add"))
    status = "ok" if can_add and max_add > 0 else "blocked"
    return {
        "version": CONTRACT_VERSION,
        "status": status,
        "action_type": action,
        "symbol": str(row.get("symbol") or normalize_symbol(symbol)),
        "scope": analysis.get("scope") or "A股红利池",
        "denominator_market_value": analysis.get("denominator_market_value"),
        "max_add_market_value": round(max_add, 2),
        "max_add_shares_estimate": add_guardrail.get("max_add_shares_estimate") or row.get("max_add_shares_estimate"),
        "max_add_round_lot_shares": add_guardrail.get("max_add_round_lot_shares") or row.get("max_add_round_lot_shares"),
        "target_status": add_guardrail.get("status") or row.get("status"),
        "target_weight": row.get("weight"),
        "target_limit_pct": row.get("limit_pct"),
        "industry": row.get("industry"),
        "industry_label": row.get("industry_label"),
        "binding_constraints": add_guardrail.get("binding_constraints") or [],
        "formula": add_guardrail.get("formula") or analysis.get("trade_guardrail_policy") or "",
        "summary": (
            f"{row.get('symbol') or normalize_symbol(symbol)} 严格可加额度上限为 {round(max_add, 2)} CNY。"
            if status == "ok"
            else f"{row.get('symbol') or normalize_symbol(symbol)} 当前不允许新增买入/加仓，严格可加额度为 0 CNY。"
        ),
        "issues": [] if status == "ok" else ["position_limit_blocks_new_buy"],
    }


def _append_trade_guardrail_note(text: str, guardrail: dict[str, Any]) -> str:
    marker = "仓位纪律校验："
    if marker in str(text or ""):
        return str(text or "")

    status = str(guardrail.get("status") or "")
    symbol = str(guardrail.get("symbol") or "目标标的")
    scope = str(guardrail.get("scope") or "A股红利池")
    lines = [marker]
    if status == "ok":
        lines.append(
            f"- {symbol} 严格可加额度上限：{_format_amount(guardrail.get('max_add_market_value'))} CNY（{scope}口径，按买入后分母计算）。"
        )
        if guardrail.get("max_add_round_lot_shares"):
            lines.append(f"- 按当前价估算，最多约 {guardrail.get('max_add_round_lot_shares')} 股整手。")
        binding = _binding_constraint_labels(guardrail)
        if binding:
            lines.append(f"- 当前卡住上限的约束：{binding}。")
        lines.append("- 若计划金额高于该上限，必须拆低金额或放弃本次加仓。")
    elif status == "blocked":
        lines.append(f"- {symbol} 严格可加额度：0 CNY。当前仓位纪律不允许新增买入/加仓。")
        binding = _binding_constraint_labels(guardrail)
        if binding:
            lines.append(f"- 卡住新增买入的约束：{binding}。")
    else:
        lines.append(f"- {guardrail.get('summary') or '缺少仓位纪律数据，不能计算严格加仓额度。'}")
        lines.append("- 在补齐该数据前，不应给出确定加仓金额。")

    prefix = str(text or "").strip()
    return f"{prefix}\n\n" + "\n".join(lines) if prefix else "\n".join(lines)


def _position_limit_analysis_from_disclosures(disclosures: list[Any]) -> dict[str, Any]:
    for disclosure in disclosures:
        if getattr(disclosure, "skill_name", "") != "portfolio_snapshot":
            continue
        result = _result_payload(disclosure)
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        analysis = data.get("position_limit_analysis")
        if isinstance(analysis, dict):
            return analysis
    return {}


def _find_position_limit_row(analysis: dict[str, Any], symbol: str) -> dict[str, Any]:
    for row in analysis.get("positions") or []:
        if isinstance(row, dict) and _same_symbol(str(row.get("symbol") or ""), symbol):
            return row
    return {}


def _same_symbol(left: str, right: str) -> bool:
    return _symbol_key(left) == _symbol_key(right)


def _symbol_key(symbol: str) -> str:
    text = normalize_symbol(str(symbol or "")).upper()
    for suffix in (".SH", ".SZ", ".SS", ".US", ".HK"):
        if text.endswith(suffix):
            return text[: -len(suffix)]
    return text


def _binding_constraint_labels(guardrail: dict[str, Any]) -> str:
    labels = [
        str(item.get("label") or item.get("constraint_id") or "").strip()
        for item in guardrail.get("binding_constraints") or []
        if isinstance(item, dict)
    ]
    return "、".join(label for label in labels if label)


def _format_amount(value: Any) -> str:
    amount = _to_float(value)
    return f"{amount:,.2f}"


def _to_float(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


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
            "market-data",
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
