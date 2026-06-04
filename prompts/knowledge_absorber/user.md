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
  "patch_operation": "replace|insert_after",
  "target_section": "必须从目标文件中逐字复制的原文锚点。replace 时为完整旧片段；insert_after 时为新增条文前方的完整原文段落。不得写描述、章节名猜测或建议位置。",
  "old_problem": "旧条文的问题或冲突点",
  "patch_markdown": "候选 Markdown 条文。replace 时写完整替换后片段；insert_after 时只写要新增的条文。",
  "auditor_opinion": "反方审计意见",
  "risk_level": "low|medium|high"
}
若找不到可逐字复制的原文锚点，conflict_type 必须为 reject，patch_markdown 留空。
如果新知识证据不足或过度情绪化，conflict_type 必须为 reject，patch_markdown 留空。
