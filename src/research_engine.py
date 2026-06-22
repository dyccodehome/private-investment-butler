"""Growth Engine research-layer MVP.

This module keeps the new research layer read-only and deterministic. It turns
Growth universe rows, symbol intel, and research dossiers into structured
research signals that scheduled reviews can consume before producing operation
advice.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any


MAX_RESEARCH_SYMBOLS = 12
MAX_EVIDENCE_ITEMS = 5


@dataclass(frozen=True)
class ThemeRule:
    theme_id: str
    theme_name: str
    keywords: tuple[str, ...]
    industry_chain: tuple[str, ...]
    profit_pool: tuple[str, ...]
    validation_points: tuple[str, ...]


@dataclass(frozen=True)
class ResearchSignal:
    ticker: str
    name: str
    theme_id: str
    theme: str
    thesis_impact: str
    valuation_view: str
    confidence: str
    risk_level: str
    evidence_strength: str
    suggested_status: str
    next_validation: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    has_position: bool = False
    asset_type: str = "stock"


@dataclass(frozen=True)
class ThemeRadarFinding:
    theme_id: str
    theme: str
    signal_count: int
    holding_count: int
    watch_count: int
    thesis_impact: str
    evidence_strength: str
    related_symbols: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class IndustryMapping:
    theme_id: str
    theme: str
    industry_chain: list[str]
    profit_pool: list[str]
    related_symbols: list[str]
    validation_points: list[str]


@dataclass(frozen=True)
class DeepResearchCandidate:
    ticker: str
    name: str
    priority: str
    reason: str
    suggested_action: str
    dossier_status: str
    next_questions: list[str] = field(default_factory=list)


THEME_RULES: tuple[ThemeRule, ...] = (
    ThemeRule(
        theme_id="ai_compute",
        theme_name="AI 算力与加速计算",
        keywords=("AI", "NVIDIA", "NVDA", "GPU", "ACCELERATED", "COMPUTE", "DATACENTER", "DATA CENTER", "CUDA"),
        industry_chain=("GPU/ASIC", "数据中心", "高速网络", "服务器与云厂商"),
        profit_pool=("训练推理芯片", "数据中心扩容", "AI 服务器与网络设备"),
        validation_points=("数据中心收入增速", "毛利率和供给约束", "大客户资本开支持续性"),
    ),
    ThemeRule(
        theme_id="ai_software",
        theme_name="AI 应用软件与工作流",
        keywords=("AI", "SOFTWARE", "SAAS", "CLOUD", "DESIGN", "WORKFLOW", "AUTOMATION", "FIGMA", "CRM"),
        industry_chain=("应用软件", "工作流自动化", "企业订阅", "AI 功能货币化"),
        profit_pool=("席位扩张", "AI credit/usage 收费", "企业客户续约与增购"),
        validation_points=("NDR/NRR", "AI 功能付费转化", "大客户留存和 ARPU"),
    ),
    ThemeRule(
        theme_id="semiconductor",
        theme_name="半导体与存储周期",
        keywords=("SEMICONDUCTOR", "BROADCOM", "AVGO", "MEMORY", "DRAM", "HBM", "CHIP", "ASIC", "WAFER"),
        industry_chain=("芯片设计", "存储", "晶圆制造", "封测", "设备材料"),
        profit_pool=("AI ASIC", "HBM/DRAM 周期", "高端封装", "半导体设备"),
        validation_points=("订单能见度", "库存周期", "ASP 和毛利率", "资本开支周期"),
    ),
    ThemeRule(
        theme_id="cloud_security",
        theme_name="云基础设施与网络安全",
        keywords=("CLOUD", "SECURITY", "ZERO TRUST", "EDGE", "NETWORK", "CYBER", "CLOUDFLARE", "NET"),
        industry_chain=("云网络", "边缘节点", "安全访问", "开发者平台"),
        profit_pool=("企业安全预算", "边缘计算", "平台型云服务"),
        validation_points=("大客户数量", "RPO/剩余履约义务", "平台 attach rate", "自由现金流"),
    ),
    ThemeRule(
        theme_id="crypto_fintech",
        theme_name="加密资产与金融科技",
        keywords=("CRYPTO", "BITCOIN", "COINBASE", "COIN", "BLOCKCHAIN", "FINTECH", "PAYMENT", "ETF"),
        industry_chain=("交易平台", "托管", "支付清算", "链上基础设施"),
        profit_pool=("交易收入", "稳定币/托管", "机构化 ETF 流量"),
        validation_points=("交易量周期", "监管事件", "费率压力", "非交易收入占比"),
    ),
    ThemeRule(
        theme_id="biotech_healthcare",
        theme_name="生物科技与医疗创新",
        keywords=("BIOTECH", "PHARMA", "DRUG", "CLINICAL", "FDA", "GENE", "THERAPY", "HEALTH"),
        industry_chain=("药物研发", "临床试验", "商业化", "医保支付"),
        profit_pool=("创新药销售", "平台授权", "适应症扩展"),
        validation_points=("临床数据", "监管节点", "现金消耗", "商业化进度"),
    ),
)


POSITIVE_TERMS = (
    "beat",
    "beats",
    "raise",
    "raised",
    "growth",
    "accelerate",
    "accelerated",
    "partnership",
    "contract",
    "launch",
    "record",
    "strong",
    "profit",
    "guidance raised",
    "超预期",
    "增长",
    "上调",
    "合作",
    "发布",
    "盈利",
)

NEGATIVE_TERMS = (
    "miss",
    "cut",
    "downgrade",
    "decline",
    "slowdown",
    "lawsuit",
    "probe",
    "investigation",
    "antitrust",
    "risk",
    "weak",
    "loss",
    "guidance cut",
    "不及预期",
    "下调",
    "放缓",
    "调查",
    "诉讼",
    "风险",
    "亏损",
)


def build_growth_research_report(
    *,
    universe_payload: dict[str, Any] | None = None,
    symbol_intel: dict[str, Any] | None = None,
    research_dossiers: dict[str, Any] | None = None,
    market_data: dict[str, Any] | None = None,
    fundamental_data: dict[str, Any] | None = None,
    as_of: date | None = None,
    max_symbols: int = MAX_RESEARCH_SYMBOLS,
    fetch_missing_context: bool = True,
) -> dict[str, Any]:
    """Build a read-only Growth research report.

    If context is not supplied, the function reads the existing provider layer.
    Tests and scheduled reviews can pass pre-fetched context to avoid duplicate
    external calls.
    """

    target_date = as_of or date.today()
    payload = universe_payload or _sync_growth_universe()
    items = _select_universe_items(payload, max_symbols=max_symbols)
    intel = symbol_intel if symbol_intel is not None else {}
    dossiers = research_dossiers if research_dossiers is not None else {}
    market = market_data if market_data is not None else {}
    fundamentals = fundamental_data if fundamental_data is not None else {}

    if fetch_missing_context:
        if symbol_intel is None:
            intel = _fetch_symbol_intel(items)
        if research_dossiers is None:
            dossiers = _fetch_research_dossiers(items)

    signals = [
        _build_signal(
            item=item,
            intel_payload=intel.get(_symbol(item)) or {},
            dossier_payload=dossiers.get(_symbol(item)) or {},
            market_payload=market.get(_symbol(item)) or {},
            fundamental_payload=_fundamental_payload(fundamentals, _symbol(item)),
        )
        for item in items
    ]
    theme_radar = _build_theme_radar(signals)
    industry_mapper = _build_industry_mapper(signals)
    deep_research_queue = _build_deep_research_queue(signals, dossiers)
    data_gaps = _data_gaps(payload, items, intel, dossiers)
    market_context_summary = _market_context_summary(market)
    fundamental_context_summary = _fundamental_context_summary(fundamentals)

    return {
        "schema_version": 1,
        "engine": "growth_research_mvp",
        "framework_id": "Growth_Engine",
        "as_of": target_date.isoformat(),
        "source_policy": "read_only; no trading; no constitution mutation; no dossier mutation",
        "source_summary": payload.get("summary") or {},
        "universe_count": len(payload.get("universe") or []),
        "analyzed_symbol_count": len(items),
        "theme_radar": [asdict(item) for item in theme_radar],
        "industry_mapper": [asdict(item) for item in industry_mapper],
        "research_signals": [asdict(item) for item in signals],
        "deep_research_queue": [asdict(item) for item in deep_research_queue],
        "market_context_summary": market_context_summary,
        "fundamental_context_summary": fundamental_context_summary,
        "data_quality": {
            "status": "has_gaps" if data_gaps else "ok",
            "limitations": data_gaps,
        },
    }


def format_growth_research_report(report: dict[str, Any]) -> str:
    """Format a Growth research report for slash commands."""

    lines = [
        "Growth Engine 投研雷达：",
        f"- 日期：{report.get('as_of')}",
        f"- universe 标的：{report.get('universe_count', 0)}，本次分析：{report.get('analyzed_symbol_count', 0)}",
        f"- 数据状态：{(report.get('data_quality') or {}).get('status') or 'unknown'}",
        "- 写入策略：只读，不下单，不改宪法，不自动写研究档案。",
    ]

    themes = list(report.get("theme_radar") or [])
    if themes:
        lines.extend(["", "主题雷达："])
        for item in themes[:6]:
            symbols = ", ".join(item.get("related_symbols") or [])
            lines.append(
                f"- {item.get('theme')}：{item.get('thesis_impact')}，"
                f"信号 {item.get('signal_count')}，持仓 {item.get('holding_count')}，{symbols}"
            )

    signals = list(report.get("research_signals") or [])
    if signals:
        lines.extend(["", "Research Signals："])
        for item in signals[:10]:
            lines.append(
                f"- {item.get('ticker')} {item.get('name')}："
                f"{item.get('theme')} / {item.get('thesis_impact')} / "
                f"{item.get('suggested_status')} / 证据 {item.get('evidence_strength')}"
            )

    queue = list(report.get("deep_research_queue") or [])
    if queue:
        lines.extend(["", "Deep Research 队列："])
        for item in queue[:8]:
            lines.append(
                f"- {item.get('ticker')}：{item.get('priority')}，"
                f"{item.get('suggested_action')}，{item.get('reason')}"
            )

    gaps = list((report.get("data_quality") or {}).get("limitations") or [])
    if gaps:
        lines.extend(["", "数据缺口："])
        for item in gaps[:8]:
            lines.append(f"- {item}")
    return "\n".join(lines)


def _sync_growth_universe() -> dict[str, Any]:
    from src.growth_universe import sync_growth_universe

    return sync_growth_universe()


def _select_universe_items(payload: dict[str, Any], *, max_symbols: int) -> list[dict[str, Any]]:
    rows = [item for item in payload.get("universe") or [] if isinstance(item, dict)]
    rows.sort(
        key=lambda item: (
            not bool(item.get("has_position")),
            not bool(item.get("is_pinned")),
            _symbol(item),
        )
    )
    return rows[:max(1, max_symbols)]


def _fetch_symbol_intel(items: list[dict[str, Any]]) -> dict[str, Any]:
    from src.market_intel import fetch_company_announcements, fetch_company_news

    result: dict[str, Any] = {}
    for item in items:
        symbol = _symbol(item)
        name = str(item.get("name") or "").strip()
        query = " ".join(part for part in [symbol, name] if part).strip()
        result[symbol] = {
            "news": fetch_company_news(symbol, market="US", query=query, limit=3),
            "announcements": fetch_company_announcements(symbol, market="US", query=query, limit=3, days=30),
        }
    return result


def _fetch_research_dossiers(items: list[dict[str, Any]]) -> dict[str, Any]:
    from src.research_dossier import build_research_dossier_snapshot

    result: dict[str, Any] = {}
    for item in items:
        symbol = _symbol(item)
        snapshot = build_research_dossier_snapshot(
            framework_id="Growth_Engine",
            symbol=symbol,
            user_query=f"{symbol} {item.get('name') or ''}".strip(),
        )
        dossier = snapshot.get("dossier") or {}
        result[symbol] = {
            "exists": bool(snapshot.get("exists")),
            "path": snapshot.get("path"),
            "freshness": snapshot.get("freshness") or {},
            "core_thesis": dossier.get("core_thesis") or "",
            "bullish_case": list(dossier.get("bullish_case") or [])[:5],
            "bearish_case": list(dossier.get("bearish_case") or [])[:5],
            "risk_points": list(dossier.get("risk_points") or [])[:5],
            "exit_conditions": list(dossier.get("exit_conditions") or [])[:5],
            "open_questions": list(dossier.get("open_questions") or [])[:5],
        }
    return result


def _build_signal(
    *,
    item: dict[str, Any],
    intel_payload: dict[str, Any],
    dossier_payload: dict[str, Any],
    market_payload: dict[str, Any],
    fundamental_payload: dict[str, Any],
) -> ResearchSignal:
    symbol = _symbol(item)
    name = str(item.get("name") or "").strip()
    combined_text = _combined_text(item, intel_payload, dossier_payload, fundamental_payload)
    theme_rule, theme_score = _classify_theme(combined_text)
    positive_score = _term_score(combined_text, POSITIVE_TERMS)
    negative_score = _term_score(combined_text, NEGATIVE_TERMS)
    intel_count = len(_intel_items(intel_payload))
    fundamental_count = _fundamental_signal_count(fundamental_payload)
    dossier_exists = bool(dossier_payload.get("exists"))
    dossier_stale = bool((dossier_payload.get("freshness") or {}).get("stale"))
    evidence_strength = _evidence_strength(dossier_exists, dossier_stale, intel_count + fundamental_count, theme_score)
    thesis_impact = _thesis_impact(positive_score, negative_score, dossier_stale, intel_count)
    valuation_view = _valuation_view(market_payload, item)
    risk_level = _risk_level(item, negative_score, dossier_payload, evidence_strength)
    confidence = _confidence(evidence_strength, negative_score)
    suggested_status = _suggested_status(
        has_position=bool(item.get("has_position")),
        thesis_impact=thesis_impact,
        valuation_view=valuation_view,
        evidence_strength=evidence_strength,
        risk_level=risk_level,
    )
    evidence = _evidence_lines(item, intel_payload, dossier_payload, fundamental_payload, positive_score, negative_score)
    next_validation = _next_validation(theme_rule, dossier_payload)

    return ResearchSignal(
        ticker=symbol,
        name=name,
        theme_id=theme_rule.theme_id,
        theme=theme_rule.theme_name,
        thesis_impact=thesis_impact,
        valuation_view=valuation_view,
        confidence=confidence,
        risk_level=risk_level,
        evidence_strength=evidence_strength,
        suggested_status=suggested_status,
        next_validation=next_validation,
        evidence=evidence,
        has_position=bool(item.get("has_position")),
        asset_type=str(item.get("asset_type") or "stock"),
    )


def _classify_theme(text: str) -> tuple[ThemeRule, int]:
    upper = text.upper()
    scored: list[tuple[int, ThemeRule]] = []
    for rule in THEME_RULES:
        score = sum(1 for keyword in rule.keywords if keyword.upper() in upper)
        scored.append((score, rule))
    scored.sort(key=lambda row: row[0], reverse=True)
    best_score, best_rule = scored[0]
    if best_score > 0:
        return best_rule, best_score
    return (
        ThemeRule(
            theme_id="unclassified_growth",
            theme_name="未分类成长观察",
            keywords=(),
            industry_chain=("待识别行业链条",),
            profit_pool=("待识别利润池",),
            validation_points=("补充研究档案", "补充新闻公告和财报验证"),
        ),
        0,
    )


def _build_theme_radar(signals: list[ResearchSignal]) -> list[ThemeRadarFinding]:
    grouped: dict[str, list[ResearchSignal]] = {}
    for signal in signals:
        grouped.setdefault(signal.theme_id, []).append(signal)

    findings: list[ThemeRadarFinding] = []
    for theme_id, rows in grouped.items():
        holding_count = sum(1 for item in rows if item.has_position)
        impact = _aggregate_impact([item.thesis_impact for item in rows])
        evidence_strength = _aggregate_evidence([item.evidence_strength for item in rows])
        evidence: list[str] = []
        for item in rows:
            evidence.extend(item.evidence[:2])
        findings.append(
            ThemeRadarFinding(
                theme_id=theme_id,
                theme=rows[0].theme,
                signal_count=len(rows),
                holding_count=holding_count,
                watch_count=len(rows) - holding_count,
                thesis_impact=impact,
                evidence_strength=evidence_strength,
                related_symbols=[item.ticker for item in rows],
                evidence=_dedupe(evidence)[:MAX_EVIDENCE_ITEMS],
            )
        )
    findings.sort(key=lambda item: (item.holding_count, item.signal_count), reverse=True)
    return findings


def _build_industry_mapper(signals: list[ResearchSignal]) -> list[IndustryMapping]:
    result: list[IndustryMapping] = []
    for theme_id in _dedupe([item.theme_id for item in signals]):
        theme_signals = [item for item in signals if item.theme_id == theme_id]
        rule = _theme_rule_by_id(theme_id)
        result.append(
            IndustryMapping(
                theme_id=theme_id,
                theme=theme_signals[0].theme,
                industry_chain=list(rule.industry_chain),
                profit_pool=list(rule.profit_pool),
                related_symbols=[item.ticker for item in theme_signals],
                validation_points=list(rule.validation_points),
            )
        )
    return result


def _build_deep_research_queue(
    signals: list[ResearchSignal],
    dossiers: dict[str, Any],
) -> list[DeepResearchCandidate]:
    queue: list[DeepResearchCandidate] = []
    for signal in signals:
        dossier = dossiers.get(signal.ticker) or {}
        exists = bool(dossier.get("exists"))
        stale = bool((dossier.get("freshness") or {}).get("stale"))
        reason = ""
        action = ""
        priority = "P3"
        if signal.has_position and not exists:
            priority = "P1"
            reason = "已有持仓但没有研究档案。"
            action = "create_dossier"
        elif signal.has_position and stale:
            priority = "P1"
            reason = "已有持仓且研究档案过期。"
            action = "refresh_dossier"
        elif signal.risk_level == "high":
            priority = "P1" if signal.has_position else "P2"
            reason = "出现高风险或负面证据信号。"
            action = "risk_review"
        elif signal.thesis_impact in {"strengthened", "weakened"}:
            priority = "P2"
            reason = "投研假设出现变化，需要更新 thesis。"
            action = "update_thesis"
        elif not exists and signal.evidence_strength != "low":
            priority = "P2"
            reason = "观察标的有可用证据但未建立研究档案。"
            action = "create_dossier"
        if not reason:
            continue
        queue.append(
            DeepResearchCandidate(
                ticker=signal.ticker,
                name=signal.name,
                priority=priority,
                reason=reason,
                suggested_action=action,
                dossier_status=_dossier_status(dossier),
                next_questions=signal.next_validation[:3],
            )
        )
    queue.sort(key=lambda item: (item.priority, item.ticker))
    return queue


def _data_gaps(
    payload: dict[str, Any],
    items: list[dict[str, Any]],
    intel: dict[str, Any],
    dossiers: dict[str, Any],
) -> list[str]:
    gaps: list[str] = []
    if not payload.get("universe"):
        gaps.append("Growth universe 为空，无法生成有效投研雷达。")
    for item in items:
        symbol = _symbol(item)
        symbol_intel = intel.get(symbol) or {}
        if not _intel_items(symbol_intel):
            gaps.append(f"{symbol} 新闻/公告为空或不可用。")
        dossier = dossiers.get(symbol) or {}
        if not dossier.get("exists"):
            gaps.append(f"{symbol} 未建立研究档案。")
        elif (dossier.get("freshness") or {}).get("stale"):
            gaps.append(f"{symbol} 研究档案已过期。")
    return _dedupe(gaps)


def _market_context_summary(market_data: dict[str, Any]) -> dict[str, Any]:
    longbridge_count = 0
    quote_count = 0
    ma120_count = 0
    for payload in market_data.values():
        if not isinstance(payload, dict):
            continue
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        snapshot = data.get("longbridge_market_snapshot") if isinstance(data.get("longbridge_market_snapshot"), dict) else {}
        if snapshot:
            longbridge_count += 1
        if data.get("current_price"):
            quote_count += 1
        if data.get("MA120") or data.get("ma120"):
            ma120_count += 1
    return {
        "symbols_with_market_data": len(market_data),
        "symbols_with_longbridge_market_snapshot": longbridge_count,
        "symbols_with_quote": quote_count,
        "symbols_with_ma120": ma120_count,
    }


def _fundamental_context_summary(fundamental_data: dict[str, Any]) -> dict[str, Any]:
    symbol_data = fundamental_data.get("symbol_data") if isinstance(fundamental_data.get("symbol_data"), dict) else {}
    return {
        "symbols_with_fundamental_data": len(symbol_data),
        "symbols_with_company_profile": sum(1 for item in symbol_data.values() if isinstance(item, dict) and item.get("company_name")),
        "symbols_with_valuation": sum(1 for item in symbol_data.values() if isinstance(item, dict) and item.get("valuation_metrics")),
        "symbols_with_consensus": sum(1 for item in symbol_data.values() if isinstance(item, dict) and item.get("consensus")),
        "symbols_with_forecast_eps": sum(1 for item in symbol_data.values() if isinstance(item, dict) and item.get("forecast_eps")),
        "symbols_with_dividend_history": sum(1 for item in symbol_data.values() if isinstance(item, dict) and item.get("dividend_count")),
    }


def _fundamental_payload(fundamental_data: dict[str, Any], symbol: str) -> dict[str, Any]:
    symbol_data = fundamental_data.get("symbol_data") if isinstance(fundamental_data.get("symbol_data"), dict) else {}
    payload = symbol_data.get(symbol) if isinstance(symbol_data, dict) else None
    return payload if isinstance(payload, dict) else {}


def _fundamental_signal_count(payload: dict[str, Any]) -> int:
    score = 0
    for key in ("company_name", "valuation_desc", "financial_report_snapshot", "forecast_eps", "consensus"):
        if payload.get(key):
            score += 1
    return score


def _combined_text(
    item: dict[str, Any],
    intel_payload: dict[str, Any],
    dossier_payload: dict[str, Any],
    fundamental_payload: dict[str, Any],
) -> str:
    parts = [
        str(item.get("symbol") or ""),
        str(item.get("name") or ""),
        str(item.get("asset_type") or ""),
        " ".join(str(value) for value in item.get("source_groups") or []),
        str(item.get("reason") or ""),
        str(dossier_payload.get("core_thesis") or ""),
        " ".join(str(value) for value in dossier_payload.get("bullish_case") or []),
        " ".join(str(value) for value in dossier_payload.get("bearish_case") or []),
        " ".join(str(value) for value in dossier_payload.get("risk_points") or []),
        str(fundamental_payload.get("company_name") or ""),
        str(fundamental_payload.get("industry") or ""),
        str(fundamental_payload.get("valuation_desc") or ""),
        _jsonish_text(fundamental_payload.get("financial_report_snapshot")),
        _jsonish_text(fundamental_payload.get("forecast_eps")),
        _jsonish_text(fundamental_payload.get("consensus")),
    ]
    for row in _intel_items(intel_payload):
        parts.extend([str(row.get("title") or row.get("text") or ""), str(row.get("summary") or "")])
    return " ".join(part for part in parts if part)


def _intel_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for key in ("news", "announcements", "filings", "topics", "longbridge_news", "longbridge_filings", "longbridge_topics"):
        block = payload.get(key)
        if isinstance(block, dict):
            data = block.get("data") if isinstance(block.get("data"), dict) else {}
            rows = block.get("items") or data.get("items") or data.get("news") or data.get("announcements") or []
            items.extend(row for row in rows if isinstance(row, dict))
    return items


def _evidence_strength(dossier_exists: bool, dossier_stale: bool, intel_count: int, theme_score: int) -> str:
    score = 0
    if dossier_exists:
        score += 2
    if dossier_stale:
        score -= 1
    if intel_count:
        score += min(2, intel_count)
    if theme_score:
        score += 1
    if score >= 4:
        return "high"
    if score >= 2:
        return "medium"
    return "low"


def _thesis_impact(positive_score: int, negative_score: int, dossier_stale: bool, intel_count: int) -> str:
    if negative_score >= max(2, positive_score + 1):
        return "weakened"
    if positive_score >= max(2, negative_score + 1):
        return "strengthened"
    if dossier_stale:
        return "needs_refresh"
    if intel_count:
        return "stable_with_updates"
    return "insufficient_evidence"


def _valuation_view(market_payload: dict[str, Any], item: dict[str, Any]) -> str:
    data = market_payload.get("data") if isinstance(market_payload.get("data"), dict) else {}
    current_price = _to_float(data.get("current_price") or item.get("current_price"))
    ma120 = _to_float(data.get("MA120") or data.get("ma120"))
    cost_price = _to_float(item.get("cost_price"))
    if current_price and ma120:
        if current_price >= ma120 * 1.25:
            return "extended_above_ma120"
        if current_price >= ma120:
            return "above_ma120"
        return "below_ma120"
    if current_price and cost_price and cost_price > 0:
        ratio = current_price / cost_price
        if ratio >= 1.4:
            return "far_above_cost"
        if ratio <= 0.85:
            return "below_cost"
        return "near_cost"
    return "unknown"


def _risk_level(
    item: dict[str, Any],
    negative_score: int,
    dossier_payload: dict[str, Any],
    evidence_strength: str,
) -> str:
    if negative_score >= 2:
        return "high"
    if str(item.get("asset_type") or "") == "etf":
        return "medium"
    if not dossier_payload.get("exists") and bool(item.get("has_position")):
        return "medium_high"
    if evidence_strength == "low":
        return "medium"
    return "medium"


def _confidence(evidence_strength: str, negative_score: int) -> str:
    if evidence_strength == "high" and negative_score == 0:
        return "medium_high"
    if evidence_strength == "medium":
        return "medium"
    return "low"


def _suggested_status(
    *,
    has_position: bool,
    thesis_impact: str,
    valuation_view: str,
    evidence_strength: str,
    risk_level: str,
) -> str:
    if risk_level == "high":
        return "trim_review" if has_position else "watch_only"
    if thesis_impact == "weakened":
        return "trim_review" if has_position else "downgrade_watch"
    if evidence_strength == "low":
        return "watch_only" if not has_position else "hold_with_research_required"
    if has_position:
        if thesis_impact == "strengthened" and valuation_view not in {"extended_above_ma120", "unknown"}:
            return "add_condition_review"
        return "hold_review"
    if thesis_impact == "strengthened" and valuation_view not in {"extended_above_ma120"}:
        return "focus_watch"
    return "watch"


def _evidence_lines(
    item: dict[str, Any],
    intel_payload: dict[str, Any],
    dossier_payload: dict[str, Any],
    fundamental_payload: dict[str, Any],
    positive_score: int,
    negative_score: int,
) -> list[str]:
    lines = []
    if item.get("has_position"):
        lines.append("长桥显示为 Growth 持仓。")
    else:
        lines.append("长桥显示为 Growth 自选/观察标的。")
    if dossier_payload.get("exists"):
        lines.append("已有研究档案可引用。")
    else:
        lines.append("尚未建立研究档案。")
    if positive_score:
        lines.append(f"正向关键词命中 {positive_score}。")
    if negative_score:
        lines.append(f"负向/风险关键词命中 {negative_score}。")
    longbridge_event_count = _longbridge_event_count(intel_payload)
    if longbridge_event_count:
        lines.append(f"长桥资讯/披露/话题命中 {longbridge_event_count} 条。")
    valuation_desc = str(fundamental_payload.get("valuation_desc") or "").strip()
    if valuation_desc:
        lines.append(f"长桥估值摘要：{valuation_desc[:120]}")
    if fundamental_payload.get("financial_report_snapshot"):
        lines.append("长桥已返回财报速览/财务摘要。")
    if fundamental_payload.get("consensus") or fundamental_payload.get("forecast_eps"):
        lines.append("长桥已返回分析师预测或一致预期。")
    for row in _intel_items(intel_payload)[:2]:
        title = str(row.get("title") or row.get("text") or "").strip()
        if title:
            lines.append(f"资讯：{title[:120]}")
    return _dedupe(lines)[:MAX_EVIDENCE_ITEMS]


def _longbridge_event_count(payload: dict[str, Any]) -> int:
    total = 0
    for key in ("longbridge_news", "longbridge_filings", "longbridge_topics"):
        block = payload.get(key)
        if isinstance(block, dict):
            total += len(block.get("items") or [])
    return total


def _jsonish_text(value: Any) -> str:
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, (list, dict)):
        return str(value)[:2000]
    return str(value)


def _next_validation(rule: ThemeRule, dossier_payload: dict[str, Any]) -> list[str]:
    questions = list(rule.validation_points)
    questions.extend(str(item) for item in dossier_payload.get("open_questions") or [])
    questions.extend(str(item) for item in dossier_payload.get("exit_conditions") or [])
    return _dedupe(questions)[:6]


def _term_score(text: str, terms: tuple[str, ...]) -> int:
    upper = text.upper()
    return sum(1 for term in terms if term.upper() in upper)


def _theme_rule_by_id(theme_id: str) -> ThemeRule:
    for rule in THEME_RULES:
        if rule.theme_id == theme_id:
            return rule
    return ThemeRule(
        theme_id=theme_id,
        theme_name="未分类成长观察",
        keywords=(),
        industry_chain=("待识别行业链条",),
        profit_pool=("待识别利润池",),
        validation_points=("补充研究档案", "补充新闻公告和财报验证"),
    )


def _aggregate_impact(values: list[str]) -> str:
    if "weakened" in values:
        return "weakened"
    if "strengthened" in values:
        return "strengthened"
    if "needs_refresh" in values:
        return "needs_refresh"
    if "stable_with_updates" in values:
        return "stable_with_updates"
    return "insufficient_evidence"


def _aggregate_evidence(values: list[str]) -> str:
    if "high" in values:
        return "high"
    if "medium" in values:
        return "medium"
    return "low"


def _dossier_status(dossier: dict[str, Any]) -> str:
    if not dossier.get("exists"):
        return "missing"
    if (dossier.get("freshness") or {}).get("stale"):
        return "stale"
    return "fresh"


def _symbol(item: dict[str, Any]) -> str:
    return str(item.get("symbol") or "").strip().upper()


def _dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        result.append(text)
        seen.add(text)
    return result


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
