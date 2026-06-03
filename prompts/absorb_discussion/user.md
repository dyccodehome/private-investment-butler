当前 patch proposal JSON：
{{patch_json}}

目标宪法全文：
{{constitution}}

完整讨论日志：
{{discussion_log}}

用户最新回复：
{{latest_user_message}}

请返回严格 JSON，字段如下：
{
  "status": "need_more_discussion|ready_to_accept|recommend_reject",
  "reply_to_user": "给用户的下一轮回复，必须简洁、直接",
  "updated_patch_markdown": "如果需要修订候选补丁，写完整候选 Markdown；否则沿用原补丁",
  "updated_target_section": "如果目标替换片段需要变化，写完整旧片段；否则沿用原 target_section",
  "decision_reason": "为什么继续讨论、建议加入或建议拒绝",
  "next_question": "如果还需要讨论，只问一个问题；否则留空"
}
如果 status 是 ready_to_accept，reply_to_user 必须明确说明用户仍需回复“同意”才会写入。
如果 status 是 recommend_reject，reply_to_user 必须明确说明用户仍需回复“拒绝”才会归档拒绝。
