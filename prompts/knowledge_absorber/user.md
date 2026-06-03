patch_id: {{patch_id}}
framework_id: {{framework_id}}

target_id: {{target_id}}
target_name: {{target_name}}
target_file: {{target_file}}

现有目标文件内容：
{{constitution}}

待吸收知识：
{{source_text}}

请返回严格 JSON，字段如下：
{
  "source_summary": "一句话概括知识来源",
  "extracted_principles": ["只保留底层逻辑因子"],
  "applicability": {"market": "", "strategy": "", "conditions": [], "invalid_when": []},
  "conflict_type": "supplement|refine|conflict|reject",
  "target_section": "目标文件中需要替换的旧片段；若只能新增则写建议插入点原文",
  "old_problem": "旧条文的问题或冲突点",
  "patch_markdown": "候选 Markdown 条文",
  "auditor_opinion": "反方审计意见",
  "risk_level": "low|medium|high"
}
如果新知识证据不足或过度情绪化，conflict_type 必须为 reject，patch_markdown 留空。
