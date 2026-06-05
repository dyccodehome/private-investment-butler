"""受 Claude Code 渐进披露启发的按需 Skill 加载器。

本模块不直接实现业务工具，只维护轻量注册表，并在管道授权披露时加载被申请的 Skill。
真实数据/API 代码后续应放在各自 Skill 边界之后。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from src.data_quality import payload_data_quality
from src.init import FRAMEWORKS_DIR, SKILLS_DIR
from src.market_intel import fetch_company_announcements, fetch_company_news
from src.portfolio_ledger import build_enriched_portfolio_snapshot
from src.research_dossier import build_research_dossier_snapshot
from src.tool_registry import ToolSpec, validate_skill_payload, validate_tool_access


@dataclass(frozen=True)
class SkillSpec:
    """定位和描述单个 Skill 所需的静态元数据。"""

    skill_id: str
    directory: str
    description: str
    entry_file: str = "SKILL.md"


@dataclass(frozen=True)
class LoadedSkill:
    """按需加载指令文件后的 Skill 对象。"""

    skill_id: str
    description: str
    path: Path
    instructions: str
    arguments: dict[str, Any]
    payload: dict[str, Any] | None = None
    tool_policy: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        """将已加载 Skill 转换为紧凑披露元数据。

        默认 payload 会刻意排除完整 ``SKILL.md`` 指令，避免每轮都把大段静态提示词喂给模型。
        路径会保留，方便后续节点在确实需要时显式重新加载完整 Skill。
        """

        base_payload = {
            "skill_id": self.skill_id,
            "description": self.description,
            "path": str(self.path),
            "arguments": self.arguments,
        }
        if self.payload is not None:
            base_payload["result"] = self.payload
        if self.tool_policy is not None:
            base_payload["tool_policy"] = self.tool_policy
        return base_payload


SKILL_ALIASES: dict[str, str] = {
    # 兼容早期管道状态的语义别名。
    "market_snapshot": "market-data",
    "negative_news": "news-search",
}

SKILL_REGISTRY: dict[str, SkillSpec] = {}


def load_skill(
    skill_id: str,
    arguments: dict[str, Any] | None = None,
    *,
    framework_id: str | None = None,
    agent_role: str = "worker",
) -> LoadedSkill:
    """当管道节点申请时，只加载指定的一个 Skill。

    调用方只会拿到这个 Skill 的内容，而不是所有可用工具。
    这就是渐进披露边界：不申请，就不加载。
    """

    spec = get_skill_spec(skill_id)
    tool_spec = ensure_skill_allowed(framework_id, spec.skill_id, agent_role=agent_role) if framework_id else None
    skill_path = SKILLS_DIR / spec.directory / spec.entry_file
    if not skill_path.exists():
        raise FileNotFoundError(f"Skill entry file not found: {skill_path}")

    payload = _normalize_skill_payload(
        spec.skill_id,
        _execute_skill_payload(spec.skill_id, arguments or {}),
        arguments or {},
        tool_spec=tool_spec,
    )
    if tool_spec:
        validate_skill_payload(payload, tool=tool_spec)

    return LoadedSkill(
        skill_id=spec.skill_id,
        description=spec.description,
        path=skill_path,
        instructions=skill_path.read_text(encoding="utf-8"),
        arguments=arguments or {},
        payload=payload,
        tool_policy=tool_spec.to_payload() if tool_spec else None,
    )


def get_skill_spec(skill_id: str) -> SkillSpec:
    """只返回注册表元数据，不加载 Skill 正文。"""

    registry = _get_registry()
    resolved_id = SKILL_ALIASES.get(skill_id, skill_id)
    if resolved_id not in registry:
        raise KeyError(f"Unknown skill: {skill_id}")
    return registry[resolved_id]


def ensure_skill_allowed(
    framework_id: str | None,
    skill_id: str,
    *,
    agent_role: str = "worker",
) -> ToolSpec:
    """校验某个策略框架是否允许披露指定 Skill。"""

    spec = get_skill_spec(skill_id)
    try:
        return validate_tool_access(
            spec.skill_id,
            framework_id=framework_id,
            agent_role=agent_role,
        ).tool
    except KeyError as exc:
        raise PermissionError(f"Skill {spec.skill_id} is not registered in Tool Registry.") from exc


def list_skill_ids() -> list[str]:
    """列出可用 Skill ID，但不读取任何 Skill 文件正文。"""

    return sorted(_get_registry())


def _get_registry() -> dict[str, SkillSpec]:
    """返回缓存的 Skill 注册表，首次使用时自动发现目录。"""

    global SKILL_REGISTRY
    if not SKILL_REGISTRY:
        SKILL_REGISTRY = _discover_skills()
    return SKILL_REGISTRY


def _discover_skills() -> dict[str, SkillSpec]:
    """扫描 ``skills/*/SKILL.md``，但不读取完整 Skill 指令。"""

    registry: dict[str, SkillSpec] = {}
    if not SKILLS_DIR.exists():
        return registry

    for skill_dir in sorted(path for path in SKILLS_DIR.iterdir() if path.is_dir()):
        entry_path = skill_dir / "SKILL.md"
        if not entry_path.exists():
            continue
        skill_id = skill_dir.name
        registry[skill_id] = SkillSpec(
            skill_id=skill_id,
            directory=skill_id,
            description=_read_frontmatter_description(entry_path) or f"加载 {skill_id} Skill。",
        )
    return registry


def _execute_skill_payload(skill_id: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """对少数本地确定性 Skill 直接执行并返回披露结果。"""

    if skill_id == "portfolio_snapshot":
        return build_enriched_portfolio_snapshot()
    if skill_id == "research_dossier":
        return build_research_dossier_snapshot(
            framework_id=arguments.get("framework_id"),
            symbol=arguments.get("symbol"),
            user_query=str(arguments.get("user_query") or ""),
        )
    if skill_id == "trade_history":
        return _build_trade_history_snapshot(arguments)
    if skill_id == "news-search":
        return _execute_news_search(arguments)
    if skill_id == "announcement-search":
        return _execute_announcement_search(arguments)
    if skill_id == "market-data":
        from src.market_data import fetch_market_data

        symbol = str(arguments.get("symbol") or arguments.get("stock_code") or arguments.get("query") or "").strip()
        if not symbol:
            return {
                "status": "error",
                "source": "market_data_provider",
                "market": str(arguments.get("market") or ""),
                "symbol": "",
                "data": {},
                "error": "缺少 symbol 参数。",
            }
        return fetch_market_data(symbol, market=arguments.get("market"))
    return None


def _normalize_skill_payload(
    skill_id: str,
    raw_payload: dict[str, Any] | None,
    arguments: dict[str, Any],
    *,
    tool_spec: ToolSpec | None = None,
) -> dict[str, Any]:
    """Wrap Skill output in a standard disclosure schema."""

    data_type = tool_spec.data_type if tool_spec else skill_id
    if raw_payload is None:
        return _standard_payload(
            status="missing",
            source="skill_registry",
            data_type=data_type,
            data={"arguments": arguments},
            warnings=["该 Skill 尚未接入可执行 payload，只披露了 Skill 元数据。"],
            error="",
        )

    if _is_standard_payload(raw_payload):
        payload = dict(raw_payload)
        payload["status"] = _normalize_status(str(payload["status"]))
        payload.setdefault("data_type", data_type)
        payload.setdefault("freshness", _freshness(raw_payload))
        payload.setdefault("warnings", [])
        payload.setdefault("error", "")
        return _with_data_quality(payload)

    status = _normalize_status(str(raw_payload.get("status") or "ok"))
    source = str(raw_payload.get("source") or _default_source(skill_id))
    error_text = str(raw_payload.get("error") or "")
    warnings = list(raw_payload.get("warnings") or [])
    data = _payload_data(raw_payload)
    return _standard_payload(
        status=status,
        source=source,
        data_type=data_type,
        data=data,
        warnings=warnings,
        error=error_text,
        freshness=_freshness(raw_payload),
        source_chain=raw_payload.get("source_chain") if isinstance(raw_payload.get("source_chain"), list) else None,
        data_quality=raw_payload.get("data_quality") if isinstance(raw_payload.get("data_quality"), dict) else None,
    )


def _standard_payload(
    *,
    status: str,
    source: str,
    data_type: str,
    data: dict[str, Any],
    warnings: list[str],
    error: str,
    freshness: dict[str, Any] | None = None,
    source_chain: list[dict[str, Any]] | None = None,
    data_quality: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "status": status,
        "source": source,
        "data_type": data_type,
        "data": data,
        "freshness": freshness or _freshness({}),
        "warnings": warnings,
        "error": error,
    }
    if source_chain is not None:
        payload["source_chain"] = source_chain
    if data_quality is not None:
        payload["data_quality"] = data_quality
    return _with_data_quality(payload)


def _is_standard_payload(payload: dict[str, Any]) -> bool:
    return {"status", "source", "data_type", "data", "freshness", "warnings", "error"}.issubset(payload)


def _normalize_status(status: str) -> str:
    if status == "not_configured":
        return "provider_not_configured"
    return status


def _payload_data(raw_payload: dict[str, Any]) -> dict[str, Any]:
    standard_keys = {
        "status",
        "source",
        "data",
        "data_type",
        "freshness",
        "warnings",
        "error",
        "source_chain",
        "data_quality",
    }
    data = {key: value for key, value in raw_payload.items() if key not in standard_keys}
    if "data" in raw_payload:
        data["payload"] = raw_payload["data"]
    return data


def _with_data_quality(payload: dict[str, Any]) -> dict[str, Any]:
    quality = payload_data_quality(payload)
    payload.setdefault("data_quality", quality)
    payload.setdefault("source_chain", quality.get("source_chain") or [])
    return payload


def _freshness(raw_payload: dict[str, Any]) -> dict[str, Any]:
    existing = raw_payload.get("freshness")
    if isinstance(existing, dict):
        return existing
    as_of = str(raw_payload.get("as_of") or datetime.now().replace(microsecond=0).isoformat())
    return {
        "as_of": as_of,
        "stale": False,
        "stale_reason": "",
    }


def _default_source(skill_id: str) -> str:
    if skill_id in {"portfolio_snapshot", "research_dossier", "trade_history"}:
        return "local"
    if skill_id == "market-data":
        return "market_data_provider"
    if skill_id == "news-search":
        return "market_intel_news"
    if skill_id == "announcement-search":
        return "market_intel_announcements"
    return "skill_registry"


def _build_trade_history_snapshot(arguments: dict[str, Any]) -> dict[str, Any]:
    """从本地会话黑匣子和研究档案中检索历史判断。"""

    symbol = str(arguments.get("symbol") or "").strip().upper()
    framework_id = str(arguments.get("framework_id") or "").strip()
    if not symbol:
        return {
            "status": "error",
            "source": "local_trade_history",
            "data": {"symbol": "", "matches": []},
            "error": "缺少 symbol 参数。",
        }

    matches: list[dict[str, Any]] = []
    for framework_dir in _iter_framework_dirs(framework_id):
        matches.extend(_chat_history_matches(framework_dir, symbol, limit=max(10 - len(matches), 0)))
        if len(matches) >= 10:
            break
        matches.extend(_dossier_decision_matches(framework_dir, symbol, limit=max(10 - len(matches), 0)))
        if len(matches) >= 10:
            break

    matches.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
    return {
        "status": "ok",
        "source": "local_trade_history",
        "data": {
            "symbol": symbol,
            "framework_id": framework_id,
            "matches": matches[:10],
            "match_count": len(matches[:10]),
        },
        "error": "",
    }


def _execute_news_search(arguments: dict[str, Any]) -> dict[str, Any]:
    """Fetch company news through free read-only providers."""

    query = _market_intel_query(arguments)
    symbol = _market_intel_symbol(arguments, query)
    return fetch_company_news(
        symbol or query,
        market=_market_intel_market(arguments),
        query=query,
        limit=_market_intel_limit(arguments),
    )


def _execute_announcement_search(arguments: dict[str, Any]) -> dict[str, Any]:
    """Fetch announcements and filings through free read-only providers."""

    query = _market_intel_query(arguments)
    symbol = _market_intel_symbol(arguments, query)
    return fetch_company_announcements(
        symbol or query,
        market=_market_intel_market(arguments),
        query=query,
        limit=_market_intel_limit(arguments),
        days=_market_intel_days(arguments),
    )


def _market_intel_query(arguments: dict[str, Any]) -> str:
    return str(arguments.get("query") or arguments.get("symbol") or arguments.get("stock_code") or "").strip()


def _market_intel_symbol(arguments: dict[str, Any], query: str) -> str:
    explicit = str(arguments.get("symbol") or arguments.get("stock_code") or "").strip().upper()
    if explicit:
        return explicit
    for token in query.replace("，", " ").replace(",", " ").split():
        clean = token.strip().strip("()（）[]【】").upper()
        if clean.isdigit() and len(clean) == 6:
            return clean
    return ""


def _market_intel_market(arguments: dict[str, Any]) -> str:
    explicit = str(arguments.get("market") or "").strip().upper()
    return "CN" if explicit in {"A", "ASHARE", "A_SHARE"} else explicit


def _market_intel_limit(arguments: dict[str, Any]) -> int:
    try:
        return max(1, min(int(arguments.get("limit") or 10), 20))
    except (TypeError, ValueError):
        return 10


def _market_intel_days(arguments: dict[str, Any]) -> int:
    try:
        return max(1, min(int(arguments.get("days") or 30), 365))
    except (TypeError, ValueError):
        return 30


def _iter_framework_dirs(framework_id: str) -> list[Path]:
    if framework_id:
        path = FRAMEWORKS_DIR / framework_id
        return [path] if path.exists() else []
    return [
        path
        for path in sorted(FRAMEWORKS_DIR.iterdir())
        if path.is_dir() and path.name != "research_templates"
    ]


def _chat_history_matches(framework_dir: Path, symbol: str, *, limit: int) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    history_dir = framework_dir / "chat_history"
    if not history_dir.exists():
        return []

    matches: list[dict[str, Any]] = []
    for path in sorted(history_dir.glob("*.jsonl"), reverse=True):
        for line in reversed(path.read_text(encoding="utf-8").splitlines()):
            if len(matches) >= limit:
                return matches
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            haystack = " ".join(
                str(record.get(key) or "")
                for key in ["user_query", "agent_proposal", "final_reply_to_user"]
            ).upper()
            if symbol not in haystack:
                continue
            matches.append(
                {
                    "source": "chat_history",
                    "framework_id": framework_dir.name,
                    "timestamp": record.get("timestamp"),
                    "context_bundle_id": record.get("context_bundle_id"),
                    "user_query": record.get("user_query"),
                    "audit_signal": record.get("audit_signal"),
                    "status": record.get("status"),
                    "final_reply_preview": _preview(record.get("final_reply_to_user")),
                }
            )
    return matches


def _dossier_decision_matches(framework_dir: Path, symbol: str, *, limit: int) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    dossier_path = framework_dir / "research_dossiers" / f"{_safe_symbol_filename(symbol)}.json"
    if not dossier_path.exists():
        return []

    try:
        data = json.loads(dossier_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []

    matches: list[dict[str, Any]] = []
    for item in reversed(data.get("decision_log") or []):
        if len(matches) >= limit:
            break
        matches.append(
            {
                "source": "research_dossier",
                "framework_id": framework_dir.name,
                "timestamp": item.get("timestamp"),
                "context_bundle_id": item.get("context_bundle_id"),
                "user_query": item.get("user_query"),
                "audit_signal": item.get("audit_signal"),
                "status": item.get("status"),
                "final_reply_preview": _preview(item.get("final_reply")),
            }
        )
    return matches


def _safe_symbol_filename(symbol: str) -> str:
    return "".join(ch for ch in symbol.upper().replace("/", "-") if ch.isalnum() or ch in "._-") or "UNKNOWN"


def _preview(value: Any, limit: int = 280) -> str:
    clean = " ".join(str(value or "").split())
    return clean[:limit]


def _read_frontmatter_description(path: Path) -> str:
    """只读取 YAML frontmatter 中的 description 行。"""

    try:
        with path.open("r", encoding="utf-8") as file:
            first_line = file.readline().strip()
            if first_line != "---":
                return ""
            for line in file:
                stripped = line.strip()
                if stripped == "---":
                    return ""
                if stripped.startswith("description:"):
                    return stripped.split(":", 1)[1].strip()
    except OSError:
        return ""
    return ""
