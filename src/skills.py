"""On-demand Skill loader inspired by Claude Code progressive disclosure.

This module does not implement business tools directly. It only keeps a small
registry and loads the requested Skill's instructions when the pipeline grants
disclosure. Real data/API code should live behind each Skill boundary later.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.init import SKILLS_DIR


@dataclass(frozen=True)
class SkillSpec:
    """Static metadata needed to locate and describe one skill."""

    skill_id: str
    directory: str
    description: str
    entry_file: str = "SKILL.md"


@dataclass(frozen=True)
class LoadedSkill:
    """A Skill after its instruction file has been loaded on demand."""

    skill_id: str
    description: str
    path: Path
    instructions: str
    arguments: dict[str, Any]

    def to_payload(self) -> dict[str, Any]:
        """Convert loaded skill content into compact disclosure metadata.

        Full ``SKILL.md`` instructions are deliberately excluded from the
        default payload to avoid feeding large static prompts to the model on
        every turn. The path is kept so a future node can explicitly reload the
        full Skill when genuinely needed.
        """

        return {
            "skill_id": self.skill_id,
            "description": self.description,
            "path": str(self.path),
            "arguments": self.arguments,
        }


SKILL_ALIASES: dict[str, str] = {
    # Backward-compatible semantic aliases for older pipeline states.
    "market_snapshot": "hithink-market-query",
    "negative_news": "news-search",
}

SKILL_REGISTRY: dict[str, SkillSpec] = {}


def load_skill(skill_id: str, arguments: dict[str, Any] | None = None) -> LoadedSkill:
    """Load exactly one Skill when a pipeline node asks for it.

    The caller receives only this Skill's instruction text, not every available
    tool. That is the progressive disclosure boundary: no request, no load.
    """

    spec = get_skill_spec(skill_id)
    skill_path = SKILLS_DIR / spec.directory / spec.entry_file
    if not skill_path.exists():
        raise FileNotFoundError(f"Skill entry file not found: {skill_path}")

    return LoadedSkill(
        skill_id=spec.skill_id,
        description=spec.description,
        path=skill_path,
        instructions=skill_path.read_text(encoding="utf-8"),
        arguments=arguments or {},
    )


def get_skill_spec(skill_id: str) -> SkillSpec:
    """Return registry metadata without loading the Skill body."""

    registry = _get_registry()
    resolved_id = SKILL_ALIASES.get(skill_id, skill_id)
    if resolved_id not in registry:
        raise KeyError(f"Unknown skill: {skill_id}")
    return registry[resolved_id]


def list_skill_ids() -> list[str]:
    """List available Skill ids without reading any Skill files."""

    return sorted(_get_registry())


def _get_registry() -> dict[str, SkillSpec]:
    """Return cached Skill registry, discovering directories on first use."""

    global SKILL_REGISTRY
    if not SKILL_REGISTRY:
        SKILL_REGISTRY = _discover_skills()
    return SKILL_REGISTRY


def _discover_skills() -> dict[str, SkillSpec]:
    """Scan ``skills/*/SKILL.md`` without reading full Skill instructions."""

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


def _read_frontmatter_description(path: Path) -> str:
    """Read only the YAML frontmatter description line, if present."""

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
