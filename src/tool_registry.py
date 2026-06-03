"""Tool governance registry for Skill and command access.

Worker Agents only request tools. The Harness Runtime checks this registry
before disclosing data or running a governed command.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from src.init import PROJECT_ROOT


TOOL_REGISTRY_PATH = PROJECT_ROOT / "configs" / "tool_registry.yaml"
STANDARD_SKILL_SCHEMA = "SkillPayload"
STANDARD_SKILL_STATUSES = {
    "ok",
    "error",
    "missing",
    "empty",
    "provider_not_configured",
    "unauthorized",
}
TOOL_ALIASES = {
    "market_snapshot": "hithink-market-query",
    "negative_news": "news-search",
}


@dataclass(frozen=True)
class ToolSpec:
    """Static governance metadata for one tool."""

    name: str
    description: str = ""
    risk_level: str = "medium"
    access_type: str = "unknown"
    allowed_frameworks: tuple[str, ...] = ()
    allowed_agents: tuple[str, ...] = ()
    allowed_commands: tuple[str, ...] = ()
    requires_human_approval: bool = False
    timeout_seconds: int = 10
    audit_level: str = "full"
    output_schema: str = STANDARD_SKILL_SCHEMA
    data_type: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def skill_id(self) -> str:
        """Compatibility alias for code that still thinks in Skill IDs."""

        return self.name

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("raw", None)
        return payload


@dataclass(frozen=True)
class ToolAccessDecision:
    """Result of a Tool Registry access check."""

    allowed: bool
    tool: ToolSpec
    reason: str = ""


def get_tool_spec(tool_name: str, *, path: Path = TOOL_REGISTRY_PATH) -> ToolSpec:
    """Return governance metadata for a registered tool."""

    registry = load_tool_registry(path)
    resolved = resolve_tool_name(tool_name)
    if resolved not in registry:
        raise KeyError(f"Unknown tool in registry: {tool_name}")
    return registry[resolved]


def validate_tool_access(
    tool_name: str,
    *,
    framework_id: str | None,
    agent_role: str,
    path: Path = TOOL_REGISTRY_PATH,
) -> ToolAccessDecision:
    """Check whether an agent may use a tool in the current framework."""

    tool = get_tool_spec(tool_name, path=path)
    if framework_id and tool.allowed_frameworks and framework_id not in tool.allowed_frameworks:
        raise PermissionError(f"Tool {tool.name} is not allowed for framework {framework_id}.")
    if agent_role and tool.allowed_agents and agent_role not in tool.allowed_agents:
        raise PermissionError(f"Tool {tool.name} is not allowed for agent role {agent_role}.")
    return ToolAccessDecision(allowed=True, tool=tool, reason="allowed_by_tool_registry")


def validate_skill_payload(payload: dict[str, Any], *, tool: ToolSpec) -> None:
    """Validate the standard Skill payload envelope."""

    if tool.output_schema != STANDARD_SKILL_SCHEMA:
        return
    required = {"status", "source", "data_type", "data", "freshness", "warnings", "error"}
    missing = required - set(payload)
    if missing:
        raise ValueError(f"Skill payload for {tool.name} missing fields: {', '.join(sorted(missing))}")
    if payload["status"] not in STANDARD_SKILL_STATUSES:
        raise ValueError(f"Skill payload for {tool.name} has invalid status: {payload['status']}")
    if not isinstance(payload["warnings"], list):
        raise ValueError(f"Skill payload for {tool.name} warnings must be a list.")
    if not isinstance(payload["freshness"], dict):
        raise ValueError(f"Skill payload for {tool.name} freshness must be an object.")


def load_tool_registry(path: Path = TOOL_REGISTRY_PATH) -> dict[str, ToolSpec]:
    """Load tool registry YAML into typed ToolSpec objects."""

    raw = _load_yaml(path)
    tools = raw.get("tools") or {}
    if not isinstance(tools, dict):
        return {}
    result: dict[str, ToolSpec] = {}
    for name, value in tools.items():
        section = value if isinstance(value, dict) else {}
        result[str(name)] = ToolSpec(
            name=str(name),
            description=str(section.get("description") or ""),
            risk_level=str(section.get("risk_level") or "medium"),
            access_type=str(section.get("access_type") or "unknown"),
            allowed_frameworks=tuple(str(item) for item in section.get("allowed_frameworks") or ()),
            allowed_agents=tuple(str(item) for item in section.get("allowed_agents") or ()),
            allowed_commands=tuple(str(item) for item in section.get("allowed_commands") or ()),
            requires_human_approval=bool(section.get("requires_human_approval", False)),
            timeout_seconds=int(section.get("timeout_seconds") or 10),
            audit_level=str(section.get("audit_level") or "full"),
            output_schema=str(section.get("output_schema") or STANDARD_SKILL_SCHEMA),
            data_type=str(section.get("data_type") or str(name)),
            raw=dict(section),
        )
    return result


def resolve_tool_name(tool_name: str) -> str:
    return TOOL_ALIASES.get(tool_name, tool_name)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        import yaml  # type: ignore

        with path.open("r", encoding="utf-8") as file:
            return yaml.safe_load(file) or {}
    except ModuleNotFoundError:
        return _load_simple_tool_yaml(path)


def _load_simple_tool_yaml(path: Path) -> dict[str, Any]:
    """Small fallback parser for this registry's simple shape."""

    result: dict[str, Any] = {"tools": {}}
    current_tool: str | None = None
    current_list_key: str | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if indent == 0 and stripped == "tools:":
            continue
        if indent == 2 and stripped.endswith(":"):
            current_tool = stripped[:-1]
            current_list_key = None
            result["tools"].setdefault(current_tool, {})
            continue
        if current_tool and indent == 4:
            key, value = _split_key_value(stripped)
            if value is None:
                result["tools"][current_tool][key] = []
                current_list_key = key
            else:
                result["tools"][current_tool][key] = _parse_scalar(value)
            continue
        if current_tool and current_list_key and indent == 6 and stripped.startswith("- "):
            result["tools"][current_tool][current_list_key].append(_parse_scalar(stripped[2:]))
    return result


def _split_key_value(text: str) -> tuple[str, str | None]:
    if ":" not in text:
        return text, None
    key, value = text.split(":", 1)
    clean = value.strip()
    return key.strip(), clean if clean else None


def _parse_scalar(value: str) -> Any:
    clean = value.strip().strip('"').strip("'")
    if clean.lower() == "true":
        return True
    if clean.lower() == "false":
        return False
    if clean.isdigit():
        return int(clean)
    return clean
