framework_id: {{framework_id}}
context_bundle_id: {{context_bundle_id}}

用户原话：
{{user_input}}

子 Agent 草案：
{{draft_decision}}

已披露数据摘要：
{{disclosed_data_summary}}

请完成闭门反方审计。输出必须遵守：
第一行只能是 [ALLOW]、[WARN]、[REJECT] 或 [HUMAN_REVIEW]。
随后用以下小标题给出简洁结论：
1. 宪法一致性
2. 事实充分性
3. 反方证据
4. 仓位与回撤风险
5. 审计结论
如果存在重大事实缺口、回撤风险不可控、或建议明显迎合用户情绪，必须输出 [REJECT]。
