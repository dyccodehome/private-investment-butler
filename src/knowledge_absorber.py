"""投资框架宪法再造管道。

该模块负责把外部碎片知识转化为可审计的宪法补丁提案：

知识输入 -> 要素提炼 -> 适用边界识别 -> 冲突检测 -> 反方审计 -> Patch JSON。

第一版只生成本地 proposal，不自动修改 constitution.md；是否写入宪法必须由人工按钮确认。
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
from src.prompts import knowledge_absorber_system_prompt, knowledge_absorber_user_prompt


VALID_FRAMEWORK_IDS = {"Cash_Anchor", "Growth_Engine"}
ABSORB_TARGETS = {
    "Cash_Anchor": ("Cash_Anchor", "constitution.md", "现金流总框架"),
    "Cash_Anchor/CN_Dividend_Income": (
        "Cash_Anchor",
        "sub_frameworks/CN_Dividend_Income.md",
        "A 股红利子框架",
    ),
    "Cash_Anchor/US_Income_Options": (
        "Cash_Anchor",
        "sub_frameworks/US_Income_Options.md",
        "美股美元收益子框架",
    ),
    "Growth_Engine": ("Growth_Engine", "constitution.md", "成长股总框架"),
    "Growth_Engine/CN_Alpha_Growth": (
        "Growth_Engine",
        "sub_frameworks/CN_Alpha_Growth.md",
        "A 股成长子框架",
    ),
    "Growth_Engine/US_Disruptive_Growth": (
        "Growth_Engine",
        "sub_frameworks/US_Disruptive_Growth.md",
        "美股成长子框架",
    ),
}


@dataclass
class PatchProposal:
    """一次宪法进化提案的结构化记录。"""

    patch_id: str
    framework_id: str
    target_id: str = ""
    target_file: str = ""
    target_name: str = ""
    status: Literal["proposed", "failed", "accepted", "discussing", "rejected"] = "proposed"
    source_summary: str = ""
    extracted_principles: list[str] = field(default_factory=list)
    applicability: dict[str, Any] = field(default_factory=dict)
    conflict_type: Literal["supplement", "refine", "conflict", "reject"] = "supplement"
    patch_operation: Literal["replace", "insert_after"] = "replace"
    target_section: str = ""
    old_problem: str = ""
    patch_markdown: str = ""
    auditor_opinion: str = ""
    risk_level: Literal["low", "medium", "high"] = "medium"
    human_decision: str | None = None
    discussion_log: list[dict[str, str]] = field(default_factory=list)
    source_excerpt: str = ""
    error: str = ""
    created_at: str = ""
    updated_at: str = ""


def parse_absorb_args(args: str) -> tuple[str, str]:
    """解析 `/absorb FRAMEWORK text` 参数。"""

    parts = args.strip().split(maxsplit=1)
    if len(parts) < 2:
        raise ValueError(absorb_usage_text())
    target_id, source_text = parts[0], parts[1].strip()
    if target_id not in ABSORB_TARGETS:
        raise ValueError(absorb_usage_text(prefix=f"未知吸收目标：{target_id}"))
    if not source_text:
        raise ValueError("请在吸收目标后提供要吸收的文本或链接。")
    return target_id, source_text


def absorb_usage_text(prefix: str | None = None) -> str:
    """返回 `/absorb` 的详细用法说明。"""

    lines = []
    if prefix:
        lines.append(prefix)
    lines.extend(
        [
            "用法：/absorb <target_id> <文章链接、摘录或你的思考>",
            "",
            "可用 target_id：",
            "- Cash_Anchor：现金流总框架，共同逻辑、资金池边界、总现金流目标",
            "- Cash_Anchor/CN_Dividend_Income：A 股红利子框架，境内红利、股息、MA120、分红税",
            "- Cash_Anchor/US_Income_Options：美股美元收益子框架，QQQI、XQQI、TQQQ、美元分红、期权收益",
            "- Growth_Engine：成长股总框架，共同逻辑、估值、增长、风控边界",
            "- Growth_Engine/CN_Alpha_Growth：A 股成长子框架，本土阿尔法、产业升级、趋势纪律",
            "- Growth_Engine/US_Disruptive_Growth：美股成长子框架，全球创新、AI、SaaS、TAM 与护城河",
            "",
            "示例：",
            "/absorb Cash_Anchor/CN_Dividend_Income 高股息不是安全边际，必须同时检查分红覆盖率和自由现金流。",
        ]
    )
    return "\n".join(lines)


def run_knowledge_absorption(framework_id: str, source_text: str, chat_id: str | None = None) -> PatchProposal:
    """运行一次宪法再造漏斗并保存 patch proposal。"""

    target = resolve_absorb_target(framework_id)
    patch_id = _new_patch_id(framework_id)
    now = _now()
    constitution_path = target_constitution_path(target["target_id"])
    constitution = constitution_path.read_text(encoding="utf-8")

    _save_knowledge_inbox(target["framework_id"], patch_id, source_text, target["target_id"])

    try:
        raw = _call_absorber_llm(
            framework_id=target["framework_id"],
            target_id=target["target_id"],
            target_name=target["target_name"],
            target_file=target["target_file"],
            constitution=constitution,
            source_text=source_text,
            patch_id=patch_id,
            chat_id=chat_id,
        )
        proposal = _proposal_from_llm_json(
            raw,
            patch_id,
            target["framework_id"],
            target_id=target["target_id"],
            target_file=target["target_file"],
            target_name=target["target_name"],
        )
    except Exception as exc:
        classified = classify_error(exc)
        proposal = PatchProposal(
            patch_id=patch_id,
            framework_id=target["framework_id"],
            target_id=target["target_id"],
            target_file=target["target_file"],
            target_name=target["target_name"],
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

    proposal.framework_id = storage_framework_id(proposal.framework_id)
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

    proposal 必须提供目标文件里的精确锚点。支持两种操作：
    - replace：用 `patch_markdown` 替换 `target_section`
    - insert_after：在 `target_section` 后插入 `patch_markdown`
    """

    requested_framework_id = framework_id
    proposal = load_patch_proposal(storage_framework_id(framework_id), patch_id)
    if not proposal.target_section or not proposal.patch_markdown:
        raise ValueError("proposal 缺少 target_section 或 patch_markdown，不能自动打入宪法。")

    target_id = proposal.target_id or requested_framework_id
    constitution_path = target_constitution_path(target_id)
    if not _git_path_is_clean(constitution_path):
        raise RuntimeError(
            f"{constitution_path} 存在未提交改动。为避免混入人工草稿，请先手动提交或整理后再打补丁。"
        )
    _apply_patch_markdown(
        constitution_path,
        operation=proposal.patch_operation,
        target_section=proposal.target_section,
        patch_content=proposal.patch_markdown,
    )
    proposal.status = "accepted"
    proposal.human_decision = "accepted"
    proposal.updated_at = _now()
    save_patch_proposal(proposal)
    archive_path = archive_patch_proposal(proposal)
    _git_commit_path(constitution_path, f"{proposal.patch_id}: Update {target_id} constitution")
    return archive_path


def mark_patch_proposal(framework_id: str, patch_id: str, status: Literal["rejected"]) -> Path:
    """把 proposal 标记为拒绝，并移动到归档区。"""

    proposal = load_patch_proposal(storage_framework_id(framework_id), patch_id)
    proposal.status = status
    proposal.human_decision = status
    proposal.updated_at = _now()
    save_patch_proposal(proposal)
    return archive_patch_proposal(proposal)


def start_patch_discussion(framework_id: str, patch_id: str) -> PatchProposal:
    """把 proposal 标记为讨论中，但不归档。"""

    proposal = load_patch_proposal(storage_framework_id(framework_id), patch_id)
    proposal.status = "discussing"
    proposal.human_decision = "discussing"
    proposal.updated_at = _now()
    proposal.discussion_log.append(
        {
            "role": "system",
            "content": "用户选择继续讨论该宪法补丁，暂不加入，也不拒绝。",
            "created_at": proposal.updated_at,
        }
    )
    save_patch_proposal(proposal)
    return proposal


def append_patch_discussion(framework_id: str, patch_id: str, role: str, content: str) -> PatchProposal:
    """追加一次补丁讨论记录。"""

    proposal = load_patch_proposal(storage_framework_id(framework_id), patch_id)
    proposal.status = "discussing"
    proposal.human_decision = "discussing"
    proposal.updated_at = _now()
    proposal.discussion_log.append(
        {
            "role": role,
            "content": content,
            "created_at": proposal.updated_at,
        }
    )
    save_patch_proposal(proposal)
    return proposal


def archive_patch_proposal(proposal: PatchProposal) -> Path:
    """把 proposal 从待审批目录复制到归档目录。"""

    proposal.framework_id = storage_framework_id(proposal.framework_id)
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
    return FRAMEWORKS_DIR / storage_framework_id(framework_id) / "patch_proposals" / f"{patch_id}.json"


def format_patch_proposal_for_user(proposal: PatchProposal) -> str:
    """生成面向飞书/CLI 的提案摘要。"""

    if proposal.status == "failed":
        return (
            f"宪法进化提案生成失败 [{proposal.patch_id}]\n"
            f"目标：{proposal.target_id or proposal.framework_id}\n"
            f"错误：{proposal.error}\n"
            f"处理建议：{proposal.auditor_opinion}"
        )

    principles = "\n".join(f"- {item}" for item in proposal.extracted_principles[:5]) or "- 无"
    return (
        f"宪法补丁提案 [{proposal.patch_id}]\n"
        f"目标：{proposal.target_id or proposal.framework_id}（{proposal.target_name or '策略框架'}）\n"
        f"目标文件：{proposal.target_file or 'constitution.md'}\n"
        f"冲突类型：{proposal.conflict_type}\n"
        f"风险等级：{proposal.risk_level}\n\n"
        f"要素提炼：\n{principles}\n\n"
        f"适用边界：{json.dumps(proposal.applicability, ensure_ascii=False)}\n\n"
        f"审计意见：{proposal.auditor_opinion}\n\n"
        f"候选补丁：\n{proposal.patch_markdown[:1200]}"
    )


def _call_absorber_llm(
    *,
    framework_id: str,
    target_id: str,
    target_name: str,
    target_file: str,
    constitution: str,
    source_text: str,
    patch_id: str,
    chat_id: str | None,
) -> str:
    client = LLMClient.for_agent("knowledge_absorber", framework_id)
    return client.complete(
        system_prompt=knowledge_absorber_system_prompt(),
        user_prompt=knowledge_absorber_user_prompt(
            patch_id=patch_id,
            framework_id=framework_id,
            target_id=target_id,
            target_name=target_name,
            target_file=target_file,
            constitution=constitution,
            source_text=source_text,
        ),
        agent_role="auditor_purist",
        call_site="knowledge_absorber.run_knowledge_absorption",
        framework_id=framework_id,
        context_bundle_id="constitution_patching",
        chat_id=chat_id,
        user_query=source_text[:500],
        trace_id=patch_id,
    )


def _proposal_from_llm_json(
    raw: str,
    patch_id: str,
    framework_id: str,
    *,
    target_id: str | None = None,
    target_file: str | None = None,
    target_name: str | None = None,
) -> PatchProposal:
    data = _extract_json_object(raw)
    conflict_type = data.get("conflict_type") if data.get("conflict_type") in {"supplement", "refine", "conflict", "reject"} else "supplement"
    risk_level = data.get("risk_level") if data.get("risk_level") in {"low", "medium", "high"} else "medium"
    patch_operation = data.get("patch_operation") if data.get("patch_operation") in {"replace", "insert_after"} else "replace"
    status = "rejected" if conflict_type == "reject" else "proposed"
    return PatchProposal(
        patch_id=patch_id,
        framework_id=framework_id,
        target_id=target_id or framework_id,
        target_file=target_file or "constitution.md",
        target_name=target_name or ABSORB_TARGETS.get(framework_id, ("", "", ""))[2],
        status=status,
        source_summary=str(data.get("source_summary") or ""),
        extracted_principles=[str(item) for item in data.get("extracted_principles") or []],
        applicability=dict(data.get("applicability") or {}),
        conflict_type=conflict_type,
        patch_operation=patch_operation,
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


def _save_knowledge_inbox(framework_id: str, patch_id: str, source_text: str, target_id: str | None = None) -> Path:
    framework_id = storage_framework_id(framework_id)
    path = FRAMEWORKS_DIR / framework_id / "knowledge_inbox" / f"{patch_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "patch_id": patch_id,
        "framework_id": framework_id,
        "target_id": target_id or framework_id,
        "received_at": _now(),
        "source_excerpt": _compact_text(source_text, 2000),
        "source_length": len(source_text),
    }
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _new_patch_id(framework_id: str) -> str:
    target = ABSORB_TARGETS.get(framework_id)
    base_framework = target[0] if target else framework_id
    prefix = {
        "Cash_Anchor": "CASH",
        "Growth_Engine": "GROWTH",
    }.get(base_framework, "PATCH")
    return f"{prefix}-{datetime.now():%Y%m%d-%H%M%S}"


def resolve_absorb_target(target_id: str) -> dict[str, str]:
    """解析吸收目标，返回存储框架和目标文件。"""

    if target_id not in ABSORB_TARGETS:
        raise ValueError(absorb_usage_text(prefix=f"未知吸收目标：{target_id}"))
    framework_id, target_file, target_name = ABSORB_TARGETS[target_id]
    return {
        "target_id": target_id,
        "framework_id": framework_id,
        "target_file": target_file,
        "target_name": target_name,
    }


def storage_framework_id(framework_id: str) -> str:
    """Return the strategy-island directory for a root or sub-framework id."""

    target = ABSORB_TARGETS.get(framework_id)
    return target[0] if target else framework_id


def target_constitution_path(target_id: str) -> Path:
    target = resolve_absorb_target(target_id)
    return FRAMEWORKS_DIR / target["framework_id"] / target["target_file"]


def _apply_patch_markdown(
    path: Path,
    *,
    operation: str,
    target_section: str,
    patch_content: str,
) -> None:
    if operation == "insert_after":
        anchor = target_section.rstrip()
        patch_text = patch_content.strip()
        if not anchor or not patch_text:
            raise ValueError("insert_after proposal 缺少 target_section 或 patch_markdown。")
        patch_markdown(path, anchor, f"{anchor}\n\n{patch_text}")
        return
    if operation == "replace":
        patch_markdown(path, target_section, patch_content)
        return
    raise ValueError(f"不支持的 patch_operation：{operation}")


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
