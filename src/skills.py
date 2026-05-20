"""受 Claude Code 渐进披露启发的按需 Skill 加载器。

本模块不直接实现业务工具，只维护轻量注册表，并在管道授权披露时加载被申请的 Skill。
真实数据/API 代码后续应放在各自 Skill 边界之后。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.init import SKILLS_DIR
from src.portfolio_ledger import build_portfolio_snapshot


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
        return base_payload


SKILL_ALIASES: dict[str, str] = {
    # 兼容早期管道状态的语义别名。
    "market_snapshot": "hithink-market-query",
    "negative_news": "news-search",
}

SKILL_REGISTRY: dict[str, SkillSpec] = {}


def load_skill(skill_id: str, arguments: dict[str, Any] | None = None) -> LoadedSkill:
    """当管道节点申请时，只加载指定的一个 Skill。

    调用方只会拿到这个 Skill 的内容，而不是所有可用工具。
    这就是渐进披露边界：不申请，就不加载。
    """

    spec = get_skill_spec(skill_id)
    skill_path = SKILLS_DIR / spec.directory / spec.entry_file
    if not skill_path.exists():
        raise FileNotFoundError(f"Skill entry file not found: {skill_path}")

    payload = _execute_skill_payload(spec.skill_id, arguments or {})

    return LoadedSkill(
        skill_id=spec.skill_id,
        description=spec.description,
        path=skill_path,
        instructions=skill_path.read_text(encoding="utf-8"),
        arguments=arguments or {},
        payload=payload,
    )


def get_skill_spec(skill_id: str) -> SkillSpec:
    """只返回注册表元数据，不加载 Skill 正文。"""

    registry = _get_registry()
    resolved_id = SKILL_ALIASES.get(skill_id, skill_id)
    if resolved_id not in registry:
        raise KeyError(f"Unknown skill: {skill_id}")
    return registry[resolved_id]


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
        return build_portfolio_snapshot()
    return None


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
