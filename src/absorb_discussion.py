"""Knowledge absorption discussion loop.

This module handles the LLM-backed conversation after the user explicitly
chooses to discuss a constitution patch proposal.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Literal

from src.error_classifier import classify_error
from src.knowledge_absorber import (
    PatchProposal,
    append_patch_discussion,
    load_patch_proposal,
    save_patch_proposal,
    target_constitution_path,
)
from src.llm_client import LLMClient
from src.prompts import absorb_discussion_system_prompt, absorb_discussion_user_prompt


@dataclass(frozen=True)
class AbsorbDiscussionResult:
    """Structured result for one discussion turn."""

    status: Literal["need_more_discussion", "ready_to_accept", "recommend_reject"]
    reply_to_user: str
    updated_patch_markdown: str = ""
    updated_target_section: str = ""
    decision_reason: str = ""
    next_question: str = ""


def run_absorb_discussion_turn(
    *,
    framework_id: str,
    patch_id: str,
    user_message: str,
    chat_id: str | None = None,
) -> AbsorbDiscussionResult:
    """Append the user's message, call the discussion LLM, persist the reply."""

    proposal = append_patch_discussion(framework_id, patch_id, "user", user_message)
    constitution = target_constitution_path(proposal.target_id or framework_id).read_text(encoding="utf-8")
    raw = _call_discussion_llm(
        proposal=proposal,
        constitution=constitution,
        latest_user_message=user_message,
        chat_id=chat_id,
    )
    result = _discussion_result_from_json(raw)
    _apply_discussion_result(framework_id, patch_id, result)
    return result


def safe_run_absorb_discussion_turn(
    *,
    framework_id: str,
    patch_id: str,
    user_message: str,
    chat_id: str | None = None,
) -> AbsorbDiscussionResult:
    """Run one discussion turn and convert LLM errors into a user-facing reply."""

    try:
        return run_absorb_discussion_turn(
            framework_id=framework_id,
            patch_id=patch_id,
            user_message=user_message,
            chat_id=chat_id,
        )
    except Exception as exc:
        classified = classify_error(exc)
        return AbsorbDiscussionResult(
            status="need_more_discussion",
            reply_to_user=(
                f"讨论暂时无法继续：{classified.user_message}\n"
                "你的补充已经记录。可以稍后继续，或回复“拒绝”结束这个补丁。"
            ),
            decision_reason=f"{classified.kind.value}: {classified.raw_message}",
        )


def _call_discussion_llm(
    *,
    proposal: PatchProposal,
    constitution: str,
    latest_user_message: str,
    chat_id: str | None,
) -> str:
    client = LLMClient.for_agent("knowledge_absorber", proposal.framework_id)
    return client.complete(
        system_prompt=absorb_discussion_system_prompt(),
        user_prompt=absorb_discussion_user_prompt(
            patch_json=json.dumps(asdict(proposal), ensure_ascii=False, indent=2),
            constitution=constitution,
            discussion_log=_format_discussion_log(proposal),
            latest_user_message=latest_user_message,
        ),
        agent_role="knowledge_absorber_discussion",
        call_site="absorb_discussion.run_absorb_discussion_turn",
        framework_id=proposal.framework_id,
        context_bundle_id="constitution_patch_discussion",
        chat_id=chat_id,
        user_query=latest_user_message[:500],
        trace_id=proposal.patch_id,
    )


def _apply_discussion_result(framework_id: str, patch_id: str, result: AbsorbDiscussionResult) -> None:
    proposal = load_patch_proposal(framework_id, patch_id)
    proposal.status = "discussing"
    proposal.human_decision = result.status
    proposal.updated_at = _now_from_proposal_module()
    if result.updated_patch_markdown:
        proposal.patch_markdown = result.updated_patch_markdown
    if result.updated_target_section:
        proposal.target_section = result.updated_target_section
    if result.decision_reason:
        proposal.auditor_opinion = result.decision_reason
    proposal.discussion_log.append(
        {
            "role": "assistant",
            "content": result.reply_to_user,
            "created_at": proposal.updated_at,
        }
    )
    save_patch_proposal(proposal)


def _discussion_result_from_json(raw: str) -> AbsorbDiscussionResult:
    data = _extract_json_object(raw)
    status = data.get("status")
    if status not in {"need_more_discussion", "ready_to_accept", "recommend_reject"}:
        status = "need_more_discussion"
    reply = str(data.get("reply_to_user") or "").strip()
    next_question = str(data.get("next_question") or "").strip()
    if not reply:
        reply = next_question or "我需要你再补充一个判断：这条规则的适用边界是什么？"
    return AbsorbDiscussionResult(
        status=status,
        reply_to_user=reply,
        updated_patch_markdown=str(data.get("updated_patch_markdown") or "").strip(),
        updated_target_section=str(data.get("updated_target_section") or "").strip(),
        decision_reason=str(data.get("decision_reason") or "").strip(),
        next_question=next_question,
    )


def _format_discussion_log(proposal: PatchProposal) -> str:
    if not proposal.discussion_log:
        return "无"
    return "\n".join(
        f"{item.get('created_at', '')} {item.get('role', '')}: {item.get('content', '')}"
        for item in proposal.discussion_log
    )


def _extract_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```").strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def _now_from_proposal_module() -> str:
    from src.knowledge_absorber import _now

    return _now()
