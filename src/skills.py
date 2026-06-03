"""受 Claude Code 渐进披露启发的按需 Skill 加载器。

本模块不直接实现业务工具，只维护轻量注册表，并在管道授权披露时加载被申请的 Skill。
真实数据/API 代码后续应放在各自 Skill 边界之后。
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib import error, request

from src.init import FRAMEWORKS_DIR, SKILLS_DIR
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
    "market_snapshot": "hithink-market-query",
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
    if skill_id == "position_snapshot":
        return _build_position_snapshot(arguments)
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
    if skill_id in {"hithink-market-query", "hithink-finance-query", "hithink-basicinfo-query"}:
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
        return payload

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
) -> dict[str, Any]:
    return {
        "status": status,
        "source": source,
        "data_type": data_type,
        "data": data,
        "freshness": freshness or _freshness({}),
        "warnings": warnings,
        "error": error,
    }


def _is_standard_payload(payload: dict[str, Any]) -> bool:
    return {"status", "source", "data_type", "data", "freshness", "warnings", "error"}.issubset(payload)


def _normalize_status(status: str) -> str:
    if status == "not_configured":
        return "provider_not_configured"
    return status


def _payload_data(raw_payload: dict[str, Any]) -> dict[str, Any]:
    standard_keys = {"status", "source", "data", "data_type", "freshness", "warnings", "error"}
    data = {key: value for key, value in raw_payload.items() if key not in standard_keys}
    if "data" in raw_payload:
        data["payload"] = raw_payload["data"]
    return data


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
    if skill_id in {"portfolio_snapshot", "position_snapshot", "research_dossier", "trade_history"}:
        return "local"
    if skill_id in {"hithink-market-query", "hithink-finance-query", "hithink-basicinfo-query"}:
        return "market_data_provider"
    if skill_id == "news-search":
        return "iwencai_news_search"
    return "skill_registry"


def _build_position_snapshot(arguments: dict[str, Any]) -> dict[str, Any]:
    """读取本地 Cash/Growth 持仓，返回结构化仓位事实。"""

    symbol = str(arguments.get("symbol") or "").strip().upper()
    cash_positions: list[dict[str, Any]] = []
    growth_positions: list[dict[str, Any]] = []

    try:
        from src.portfolio_ledger import read_holdings

        for item in read_holdings():
            if not symbol or item.symbol.upper() == symbol:
                cash_positions.append(asdict(item))
    except Exception as exc:
        return {
            "status": "error",
            "source": "local_position_snapshot",
            "data": {"symbol": symbol, "cash_anchor": [], "growth_engine": []},
            "error": f"Cash Anchor 持仓读取失败：{exc}",
        }

    try:
        from src.growth_portfolio import read_growth_holdings

        for item in read_growth_holdings():
            if not symbol or item.symbol.upper() == symbol:
                growth_positions.append(asdict(item))
    except Exception as exc:
        return {
            "status": "error",
            "source": "local_position_snapshot",
            "data": {"symbol": symbol, "cash_anchor": cash_positions, "growth_engine": []},
            "error": f"Growth Engine 持仓读取失败：{exc}",
        }

    return {
        "status": "ok",
        "source": "local_position_snapshot",
        "data": {
            "symbol": symbol,
            "cash_anchor": cash_positions,
            "growth_engine": growth_positions,
        },
        "error": "",
    }


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
    """调用同花顺问财新闻搜索；无凭据时返回明确未配置状态。"""

    query = str(arguments.get("query") or arguments.get("symbol") or arguments.get("stock_code") or "").strip()
    if not query:
        return {
            "status": "error",
            "source": "iwencai_news_search",
            "data": {"query": "", "items": []},
            "error": "缺少 query 参数。",
        }

    api_key = os.getenv("IWENCAI_API_KEY", "").strip()
    if not api_key:
        return {
            "status": "not_configured",
            "source": "iwencai_news_search",
            "data": {"query": query, "items": []},
            "error": "缺少 IWENCAI_API_KEY，未执行新闻搜索。",
        }

    api_url = os.getenv("IWENCAI_API_URL", "https://openapi.iwencai.com/v1/comprehensive/search").strip()
    payload = {
        "channels": ["news"],
        "app_id": "AIME_SKILL",
        "query": query,
    }
    req = request.Request(
        api_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=20) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return {
            "status": "error",
            "source": "iwencai_news_search",
            "data": {"query": query, "items": []},
            "error": f"同花顺问财新闻搜索 HTTP {exc.code}: {detail[:300]}",
        }
    except Exception as exc:
        return {
            "status": "error",
            "source": "iwencai_news_search",
            "data": {"query": query, "items": []},
            "error": f"同花顺问财新闻搜索失败：{exc}",
        }

    status_code = raw.get("status_code", raw.get("code", 0))
    if status_code not in (0, "0", None):
        return {
            "status": "error",
            "source": "iwencai_news_search",
            "data": {"query": query, "items": [], "raw_keys": sorted(raw.keys())},
            "error": str(raw.get("status_msg") or raw.get("message") or raw.get("msg") or "新闻搜索接口返回错误。"),
        }

    items = _extract_news_items(raw)
    return {
        "status": "ok" if items else "empty",
        "source": "iwencai_news_search",
        "data": {
            "query": query,
            "items": items[:10],
            "raw_keys": sorted(raw.keys()),
        },
        "error": "" if items else "新闻搜索没有返回可用条目。",
    }


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


def _extract_news_items(raw: dict[str, Any]) -> list[dict[str, str]]:
    rows = _find_first_list(raw, keys=("datas", "results", "items", "list", "news"))
    items: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = {
            "title": _first_text(row, "title", "新闻标题", "name", "标题"),
            "summary": _first_text(row, "summary", "abstract", "content", "摘要", "内容"),
            "source": _first_text(row, "source", "media", "origin", "来源", "媒体"),
            "published_at": _first_text(row, "publish_time", "published_at", "date", "time", "发布时间"),
            "url": _first_text(row, "url", "link", "href", "新闻链接"),
        }
        if any(item.values()):
            items.append(item)
    return items


def _find_first_list(value: Any, *, keys: tuple[str, ...]) -> list[Any]:
    if isinstance(value, list):
        return value
    if not isinstance(value, dict):
        return []
    for key in keys:
        candidate = value.get(key)
        if isinstance(candidate, list):
            return candidate
    for child in value.values():
        candidate = _find_first_list(child, keys=keys)
        if candidate:
            return candidate
    return []


def _first_text(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


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
