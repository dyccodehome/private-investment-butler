"""投资框架宪法再造管道。

该模块负责把外部碎片知识转化为可审计的宪法补丁提案：

知识输入 -> 要素提炼 -> 适用边界识别 -> 冲突检测 -> 反方审计 -> Patch JSON。

第一版只生成本地 proposal，不自动修改 constitution.md；是否打入宪法必须由人类按钮裁决。
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from src.error_classifier import classify_error
from src.file_io import patch_markdown
from src.init import FRAMEWORKS_DIR, PROJECT_ROOT
from src.llm_client import LLMClient


VALID_FRAMEWORK_IDS = {"Cash_Anchor", "CN_Alpha_Growth", "US_Disruptive_Growth"}


@dataclass
class PatchProposal:
    """一次宪法进化提案的结构化记录。"""

    patch_id: str
    framework_id: str
    status: Literal["proposed", "failed", "accepted", "observing", "rejected"] = "proposed"
    source_summary: str = ""
    extracted_principles: list[str] = field(default_factory=list)
    applicability: dict[str, Any] = field(default_factory=dict)
    conflict_type: Literal["supplement", "refine", "conflict", "reject"] = "supplement"
    target_section: str = ""
    old_problem: str = ""
    patch_markdown: str = ""
    auditor_opinion: str = ""
    risk_level: Literal["low", "medium", "high"] = "medium"
    human_decision: str | None = None
    source_excerpt: str = ""
    error: str = ""
    created_at: str = ""
    updated_at: str = ""


def parse_absorb_args(args: str) -> tuple[str, str]:
    """解析 `/absorb FRAMEWORK text` 参数。"""

    parts = args.strip().split(maxsplit=1)
    if len(parts) < 2:
        raise ValueError("用法：/absorb <framework_id> <文章链接、摘录或你的思考>")
    framework_id, source_text = parts[0], parts[1].strip()
    if framework_id not in VALID_FRAMEWORK_IDS:
        raise ValueError(
            "未知策略框架。可用：Cash_Anchor, CN_Alpha_Growth, US_Disruptive_Growth"
        )
    if not source_text:
        raise ValueError("请在 framework_id 后提供要吸收的文本或链接。")
    return framework_id, source_text


def run_knowledge_absorption(framework_id: str, source_text: str, chat_id: str | None = None) -> PatchProposal:
    """运行一次宪法再造漏斗并保存 patch proposal。"""

    patch_id = _new_patch_id(framework_id)
    now = _now()
    framework_dir = FRAMEWORKS_DIR / framework_id
    constitution_path = framework_dir / "constitution.md"
    constitution = constitution_path.read_text(encoding="utf-8")

    _save_knowledge_inbox(framework_id, patch_id, source_text)

    try:
        raw = _call_absorber_llm(
            framework_id=framework_id,
            constitution=constitution,
            source_text=source_text,
            patch_id=patch_id,
            chat_id=chat_id,
        )
        proposal = _proposal_from_llm_json(raw, patch_id, framework_id)
    except Exception as exc:
        classified = classify_error(exc)
        proposal = PatchProposal(
            patch_id=patch_id,
            framework_id=framework_id,
            status="failed",
            source_summary=_compact_text(source_text, 220),
            source_excerpt=_compact_text(source_text, 600),
            error=f"{classified.kind.value}: {classified.raw_message}",
            auditor_opinion=classified.user_message,
            created_at=now,
            updated_at=now,
        )

    proposal.created_at = proposal.created_at or now
    proposal.updated_at = now
    proposal.source_excerpt = proposal.source_excerpt or _compact_text(source_text, 600)
    save_patch_proposal(proposal)
    return proposal


def save_patch_proposal(proposal: PatchProposal) -> Path:
    """保存 patch proposal 到目标策略岛。"""

    path = patch_proposal_path(proposal.framework_id, proposal.patch_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(proposal), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_patch_proposal(framework_id: str, patch_id: str) -> PatchProposal:
    """读取一个 patch proposal。"""

    path = patch_proposal_path(framework_id, patch_id)
    data = json.loads(path.read_text(encoding="utf-8"))
    return PatchProposal(**data)


def accept_patch_proposal(framework_id: str, patch_id: str) -> Path:
    """把已审批补丁打入 constitution.md，并归档 proposal。

    当前采用精确替换：proposal 必须提供 `target_section` 中的旧片段。
    如果旧片段不存在，拒绝静默写入，避免误改宪法。
    """

    proposal = load_patch_proposal(framework_id, patch_id)
    if not proposal.target_section or not proposal.patch_markdown:
        raise ValueError("proposal 缺少 target_section 或 patch_markdown，不能自动打入宪法。")

    constitution_path = FRAMEWORKS_DIR / framework_id / "constitution.md"
    if not _git_path_is_clean(constitution_path):
        raise RuntimeError(
            f"{constitution_path} 存在未提交改动。为避免混入人工草稿，请先手动提交或整理后再打补丁。"
        )
    patch_markdown(constitution_path, proposal.target_section, proposal.patch_markdown)
    proposal.status = "accepted"
    proposal.human_decision = "accepted"
    proposal.updated_at = _now()
    save_patch_proposal(proposal)
    archive_path = archive_patch_proposal(proposal)
    _git_commit_path(constitution_path, f"{proposal.patch_id}: Update {framework_id} constitution")
    return archive_path


def mark_patch_proposal(framework_id: str, patch_id: str, status: Literal["observing", "rejected"]) -> Path:
    """把 proposal 标记为观察或拒绝，并移动到归档区。"""

    proposal = load_patch_proposal(framework_id, patch_id)
    proposal.status = status
    proposal.human_decision = status
    proposal.updated_at = _now()
    save_patch_proposal(proposal)
    return archive_patch_proposal(proposal)


def archive_patch_proposal(proposal: PatchProposal) -> Path:
    """把 proposal 从待审批目录复制到归档目录。"""

    archive_path = (
        FRAMEWORKS_DIR
        / proposal.framework_id
        / "patch_archive"
        / f"{proposal.patch_id}-{proposal.status}.json"
    )
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_text(json.dumps(asdict(proposal), ensure_ascii=False, indent=2), encoding="utf-8")
    return archive_path


def patch_proposal_path(framework_id: str, patch_id: str) -> Path:
    return FRAMEWORKS_DIR / framework_id / "patch_proposals" / f"{patch_id}.json"


def format_patch_proposal_for_user(proposal: PatchProposal) -> str:
    """生成面向飞书/CLI 的提案摘要。"""

    if proposal.status == "failed":
        return (
            f"宪法进化提案生成失败 [{proposal.patch_id}]\n"
            f"目标框架：{proposal.framework_id}\n"
            f"错误：{proposal.error}\n"
            f"处理建议：{proposal.auditor_opinion}"
        )

    principles = "\n".join(f"- {item}" for item in proposal.extracted_principles[:5]) or "- 无"
    return (
        f"⚖️ 宪法进化提案 [{proposal.patch_id}]\n"
        f"目标框架：{proposal.framework_id}\n"
        f"冲突类型：{proposal.conflict_type}\n"
        f"风险等级：{proposal.risk_level}\n\n"
        f"🔍 要素提炼：\n{principles}\n\n"
        f"📌 适用边界：{json.dumps(proposal.applicability, ensure_ascii=False)}\n\n"
        f"⚖️ 审计意见：{proposal.auditor_opinion}\n\n"
        f"🛠️ 候选补丁：\n{proposal.patch_markdown[:1200]}"
    )


def _call_absorber_llm(
    *,
    framework_id: str,
    constitution: str,
    source_text: str,
    patch_id: str,
    chat_id: str | None,
) -> str:
    client = LLMClient.for_framework(framework_id)
    return client.complete(
        system_prompt=(
            "你是私人投资管家的宪法再造官。你的职责不是保存文章，而是把外部碎片知识"
            "提炼为可审计、可执行、可拒绝的投资框架补丁。"
            "必须过滤情绪、故事、个股传闻和时代噪音。"
            "必须检查新知识与现有 constitution 的关系：补充、细化、冲突或拒绝。"
            "必须扮演反方审计官，指出幸存者偏差、过拟合、适用边界和风险。"
            "只返回 JSON，不要返回 Markdown 包裹。"
        ),
        user_prompt=(
            f"patch_id: {patch_id}\n"
            f"framework_id: {framework_id}\n\n"
            f"现有 Constitution.md：\n{constitution}\n\n"
            f"待吸收知识：\n{source_text}\n\n"
            "请返回严格 JSON，字段如下：\n"
            "{\n"
            '  "source_summary": "一句话概括知识来源",\n'
            '  "extracted_principles": ["只保留底层逻辑因子"],\n'
            '  "applicability": {"market": "", "strategy": "", "conditions": [], "invalid_when": []},\n'
            '  "conflict_type": "supplement|refine|conflict|reject",\n'
            '  "target_section": "constitution.md 中需要替换的旧片段；若只能新增则写建议插入点原文",\n'
            '  "old_problem": "旧条文的问题或冲突点",\n'
            '  "patch_markdown": "候选 Markdown 条文",\n'
            '  "auditor_opinion": "反方审计意见",\n'
            '  "risk_level": "low|medium|high"\n'
            "}\n"
            "如果新知识证据不足或过度情绪化，conflict_type 必须为 reject，patch_markdown 留空。"
        ),
        agent_role="knowledge_absorber",
        call_site="knowledge_absorber.run_knowledge_absorption",
        framework_id=framework_id,
        context_bundle_id="constitution_patching",
        chat_id=chat_id,
        user_query=source_text[:500],
    )


def _proposal_from_llm_json(raw: str, patch_id: str, framework_id: str) -> PatchProposal:
    data = _extract_json_object(raw)
    conflict_type = data.get("conflict_type") if data.get("conflict_type") in {"supplement", "refine", "conflict", "reject"} else "supplement"
    risk_level = data.get("risk_level") if data.get("risk_level") in {"low", "medium", "high"} else "medium"
    status = "rejected" if conflict_type == "reject" else "proposed"
    return PatchProposal(
        patch_id=patch_id,
        framework_id=framework_id,
        status=status,
        source_summary=str(data.get("source_summary") or ""),
        extracted_principles=[str(item) for item in data.get("extracted_principles") or []],
        applicability=dict(data.get("applicability") or {}),
        conflict_type=conflict_type,
        target_section=str(data.get("target_section") or ""),
        old_problem=str(data.get("old_problem") or ""),
        patch_markdown=str(data.get("patch_markdown") or ""),
        auditor_opinion=str(data.get("auditor_opinion") or ""),
        risk_level=risk_level,
    )


def _extract_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def _save_knowledge_inbox(framework_id: str, patch_id: str, source_text: str) -> Path:
    path = FRAMEWORKS_DIR / framework_id / "knowledge_inbox" / f"{patch_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "patch_id": patch_id,
        "framework_id": framework_id,
        "received_at": _now(),
        "source_excerpt": _compact_text(source_text, 2000),
        "source_length": len(source_text),
    }
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _new_patch_id(framework_id: str) -> str:
    prefix = {
        "Cash_Anchor": "CASH",
        "CN_Alpha_Growth": "CNAG",
        "US_Disruptive_Growth": "USDG",
    }.get(framework_id, "PATCH")
    return f"{prefix}-{datetime.now():%Y%m%d-%H%M%S}"


def _compact_text(text: str, limit: int) -> str:
    clean = " ".join(text.strip().split())
    return clean[:limit]


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def _git_path_is_clean(path: Path) -> bool:
    unstaged = subprocess.run(
        ["git", "diff", "--quiet", "--", str(path.relative_to(PROJECT_ROOT))],
        cwd=PROJECT_ROOT,
        check=False,
    )
    staged = subprocess.run(
        ["git", "diff", "--cached", "--quiet", "--", str(path.relative_to(PROJECT_ROOT))],
        cwd=PROJECT_ROOT,
        check=False,
    )
    return unstaged.returncode == 0 and staged.returncode == 0


def _git_commit_path(path: Path, message: str) -> None:
    relative = str(path.relative_to(PROJECT_ROOT))
    subprocess.run(["git", "add", relative], cwd=PROJECT_ROOT, check=True)
    subprocess.run(["git", "commit", "-m", message, "--", relative], cwd=PROJECT_ROOT, check=True)
