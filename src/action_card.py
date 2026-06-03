"""Standard Action Card formatting helpers.

Action Cards are concise execution-facing summaries. They are especially useful
when an audit warning or rejection should become explicit allowed/forbidden
actions rather than a long narrative.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ActionCard:
    title: str
    conclusion: str
    current_state: list[str] = field(default_factory=list)
    allowed_actions: list[str] = field(default_factory=list)
    forbidden_actions: list[str] = field(default_factory=list)
    trigger_rules: list[str] = field(default_factory=list)
    audit_notes: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)

    def to_markdown(self) -> str:
        sections = [
            f"# {self.title}",
            "## 结论\n" + self.conclusion,
            _section("当前状态", self.current_state),
            _section("允许动作", self.allowed_actions),
            _section("禁止动作", self.forbidden_actions),
            _section("触发规则", self.trigger_rules),
            _section("反方审计", self.audit_notes),
            _section("后续动作", self.next_actions),
        ]
        return "\n\n".join(section for section in sections if section.strip())


def _section(title: str, rows: list[str]) -> str:
    if not rows:
        return ""
    return "## " + title + "\n" + "\n".join(f"- {item}" for item in rows)
