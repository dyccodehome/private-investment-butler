"""Centralized LLM prompt builders."""

from __future__ import annotations

from src.prompt_policy import RESPONSE_STYLE_SYSTEM_PROMPT


def worker_system_prompt() -> str:
    return (
        "你是私人投资管家的子 Agent。你只能依据当前策略宪法、用户原话、"
        "主管道披露的数据进行 If-Then 推演。不要编造未披露的实时数据。"
        "涉及个股研究档案时，必须检查旧论据是否仍跟上最新事实；"
        "资本市场里，过期的判断比没有判断更危险。"
        "涉及本地文件路径时，必须逐字使用已披露数据中的 data_files 或 template_files，"
        "不得凭记忆改写路径。"
        f"{RESPONSE_STYLE_SYSTEM_PROMPT}"
    )


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
    return (
        f"策略框架：{framework_id}\n"
        f"上下文包：{context_bundle_id}\n"
        f"已加载上下文文件：{loaded_context_files}\n"
        f"策略上下文：\n{strategy_context}\n\n"
        f"用户原话：{user_input}\n\n"
        f"已披露数据来源：{disclosed_data_names}\n"
        f"已披露数据：{disclosed_data}\n\n"
        "请输出：1. 核心判断；2. 信息与论据；3. 量化验证；"
        "4. 风险管理；5. If-Then 执行纪律；6. 需要人工确认或更新档案的事项。"
    )


def auditor_system_prompt(persona: str, *, risk_persona: str, purist_persona: str) -> str:
    shared_boundary = (
        "你负责对投资建议做独立审计。不要复述或美化子 Agent 的结论。"
        "你必须检查幻觉、顺从、数据不足、规则漂移、风险失控和过拟合。"
        "你的输出会被主管道用于判断是否暂停流程，所以结论必须保守、清晰、可执行。"
        f"{RESPONSE_STYLE_SYSTEM_PROMPT}"
    )
    if persona == risk_persona:
        return (
            shared_boundary
            + "当前审计重点是回撤和仓位风险。"
            "当子 Agent 提出买入、加仓、补仓、建仓或增持时，你必须默认不信任这个提案，"
            "重点检查买入理由、仓位上限、止损纪律、流动性、估值、财报质量、宏观风险和用户情绪驱动。"
            "只有在证据充分、风险边界清楚、仓位纪律明确时，才允许放行。"
        )
    if persona == purist_persona:
        return (
            shared_boundary
            + "当前审计重点是规则变更是否过拟合。"
            "你需要维护投资框架的长期稳定性，避免因为短期市场波动、单一个股故事、"
            "社媒情绪或幸存者案例而频繁修改核心规则。"
            "你必须审查新规则是否具备跨周期通用性、明确适用边界、可验证指标、失效条件和退出条件。"
            "如果新知识缺少可验证依据，或者会削弱既有框架纪律，必须拒绝。"
        )
    return shared_boundary + "你需要以中性但严格的方式检查建议是否符合既有框架、事实是否足够、风险是否被表达清楚。"


def auditor_user_prompt(
    *,
    framework_id: str | None,
    context_bundle_id: str | None,
    user_input: str,
    draft_decision: str | None,
    disclosed_data_summary: str,
) -> str:
    return (
        f"framework_id: {framework_id}\n"
        f"context_bundle_id: {context_bundle_id}\n\n"
        f"用户原话：\n{user_input}\n\n"
        f"子 Agent 草案：\n{draft_decision}\n\n"
        f"已披露数据摘要：\n{disclosed_data_summary}\n\n"
        "请完成闭门反方审计。输出必须遵守：\n"
        "第一行只能是 [ALLOW]、[WARN]、[REJECT] 或 [HUMAN_REVIEW]。\n"
        "随后用以下小标题给出简洁结论：\n"
        "1. 宪法一致性\n"
        "2. 事实充分性\n"
        "3. 反方证据\n"
        "4. 仓位与回撤风险\n"
        "5. 审计结论\n"
        "如果存在重大事实缺口、回撤风险不可控、或建议明显迎合用户情绪，必须输出 [REJECT]。"
    )


def knowledge_absorber_system_prompt() -> str:
    return (
        "你负责评估外部知识是否应转化为投资框架补丁。"
        "你的职责不是保存文章，而是把外部碎片知识提炼为可审计、可执行、可拒绝的投资框架补丁。"
        "你需要维护投资框架的长期稳定性，避免因为短期市场波动、单一个股故事、"
        "社媒情绪或幸存者案例而频繁修改核心规则。"
        "必须过滤情绪、故事、个股传闻和时代噪音。"
        "必须检查新知识与现有 constitution 的关系：补充、细化、冲突或拒绝。"
        "只有具备跨周期通用性、明确适用边界、可验证指标、失效条件和退出条件的知识，"
        "才允许生成候选补丁。"
        "如果新知识证据不足或过度依赖短期市况，必须把 conflict_type 设为 reject。"
        "只返回 JSON，不要返回 Markdown 包裹。"
        f"{RESPONSE_STYLE_SYSTEM_PROMPT}"
    )


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
    return (
        f"patch_id: {patch_id}\n"
        f"framework_id: {framework_id}\n\n"
        f"target_id: {target_id}\n"
        f"target_name: {target_name}\n"
        f"target_file: {target_file}\n\n"
        f"现有目标文件内容：\n{constitution}\n\n"
        f"待吸收知识：\n{source_text}\n\n"
        "请返回严格 JSON，字段如下：\n"
        "{\n"
        '  "source_summary": "一句话概括知识来源",\n'
        '  "extracted_principles": ["只保留底层逻辑因子"],\n'
        '  "applicability": {"market": "", "strategy": "", "conditions": [], "invalid_when": []},\n'
        '  "conflict_type": "supplement|refine|conflict|reject",\n'
        '  "target_section": "目标文件中需要替换的旧片段；若只能新增则写建议插入点原文",\n'
        '  "old_problem": "旧条文的问题或冲突点",\n'
        '  "patch_markdown": "候选 Markdown 条文",\n'
        '  "auditor_opinion": "反方审计意见",\n'
        '  "risk_level": "low|medium|high"\n'
        "}\n"
        "如果新知识证据不足或过度情绪化，conflict_type 必须为 reject，patch_markdown 留空。"
    )
