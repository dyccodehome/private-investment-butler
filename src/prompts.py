"""Prompt template loading and rendering.

Prompt bodies live under ``prompts/`` so system and user prompts can be reviewed
without editing Python code. This module keeps stable builder functions for the
rest of the application.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from src.init import PROJECT_ROOT


PROMPTS_DIR = PROJECT_ROOT / "prompts"


def worker_system_prompt() -> str:
    return _render("worker/system.md")


def worker_user_prompt(
    *,
    framework_id: str | None,
    context_bundle_id: str | None,
    loaded_context_files: list[str],
    strategy_context: str,
    user_input: str,
    disclosed_data_names: str,
    disclosed_data: str,
) -> str:
    return _render(
        "worker/user.md",
        framework_id=framework_id,
        context_bundle_id=context_bundle_id,
        loaded_context_files=loaded_context_files,
        strategy_context=strategy_context,
        user_input=user_input,
        disclosed_data_names=disclosed_data_names,
        disclosed_data=disclosed_data,
    )


def auditor_system_prompt(persona: str, *, risk_persona: str, purist_persona: str) -> str:
    if persona == risk_persona:
        persona_template = "auditor/system_risk.md"
    elif persona == purist_persona:
        persona_template = "auditor/system_purist.md"
    else:
        persona_template = "auditor/system_neutral.md"
    return _join(_render("auditor/system_base.md"), _render(persona_template))


def auditor_user_prompt(
    *,
    framework_id: str | None,
    context_bundle_id: str | None,
    user_input: str,
    draft_decision: str | None,
    disclosed_data_summary: str,
) -> str:
    return _render(
        "auditor/user.md",
        framework_id=framework_id,
        context_bundle_id=context_bundle_id,
        user_input=user_input,
        draft_decision=draft_decision,
        disclosed_data_summary=disclosed_data_summary,
    )


def knowledge_absorber_system_prompt() -> str:
    return _render("knowledge_absorber/system.md")


def knowledge_absorber_user_prompt(
    *,
    patch_id: str,
    framework_id: str,
    target_id: str,
    target_name: str,
    target_file: str,
    constitution: str,
    source_text: str,
) -> str:
    return _render(
        "knowledge_absorber/user.md",
        patch_id=patch_id,
        framework_id=framework_id,
        target_id=target_id,
        target_name=target_name,
        target_file=target_file,
        constitution=constitution,
        source_text=source_text,
    )


def absorb_discussion_system_prompt() -> str:
    return _render("absorb_discussion/system.md")


def absorb_discussion_user_prompt(
    *,
    patch_json: str,
    constitution: str,
    discussion_log: str,
    latest_user_message: str,
) -> str:
    return _render(
        "absorb_discussion/user.md",
        patch_json=patch_json,
        constitution=constitution,
        discussion_log=discussion_log,
        latest_user_message=latest_user_message,
    )


def growth_review_system_prompt() -> str:
    return _render("growth_review/system.md")


def growth_review_user_prompt(
    *,
    review_type: str,
    market: str,
    symbol: str,
    strategy_context: str,
    snapshot_json: str,
) -> str:
    return _render(
        "growth_review/user.md",
        review_type=review_type,
        market=market,
        symbol_or_all=symbol or "全部",
        strategy_context=strategy_context,
        snapshot_json=snapshot_json,
    )


def _render(relative_path: str, **values: Any) -> str:
    replacements = {"response_style": _template("shared/response_style.md"), **values}
    text = _template(relative_path)
    for key, value in replacements.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text.strip()


@lru_cache(maxsize=None)
def _template(relative_path: str) -> str:
    path = PROMPTS_DIR / relative_path
    return path.read_text(encoding="utf-8")


def _join(*parts: str) -> str:
    return "\n\n".join(part.strip() for part in parts if part.strip())
