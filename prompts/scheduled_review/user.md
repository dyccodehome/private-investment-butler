<!-- Prompt path: prompts/scheduled_review/user.md -->

请根据下面的定时任务上下文生成投资复盘或操作计划。

任务信息：
- framework_id: {{framework_id}}
- market: {{market}}
- workflow_type: {{workflow_type}}
- review_date: {{review_date}}

要求：
- 开盘前计划必须引用上一交易日收盘复盘和最近周计划；没有记录时明确说明缺口。
- 收盘后复盘必须关注上一交易日记录，并说明今天的判断是延续、修正还是失效。
- 周复盘必须按策略岛汇总过去一周日报，并给出下周计划和是否需要修改框架。
- 严格使用 review_date 作为报告日期；不要使用运行机器当天日期替代。
- Cash Anchor 输出时重点关注分红安全、现金流、仓位上限、正式披露和到账流水。
- Growth Engine 输出时重点关注增长逻辑、Research Signal、趋势纪律、估值、基本面变化和风控触发。
- Growth Engine 的自选股只允许输出观察、重点观察、买入观察区、禁动或研究档案刷新建议；没有 Action Permission 前不能给出直接买入表达。
- 若上下文存在 operation_framework，持仓处理和自选股观察必须引用其中的 action_permission.permission_result 与 operation_plans.action。
- 对 WAIT/WATCH/WARN/REJECT 的标的，只能给等待、观察、风险复核或不操作建议。
- 不要复述上下文 JSON；只提炼事实变化、判断变化和可检查动作。
- 对每个建议动作必须说明触发条件和撤销条件。
- 如果某个结论主要来自缺失研究档案，必须同时写出“当前不能做什么”，避免变成空泛的补档建议。
- 输出必须先给“结构化判断摘要”，再给“正式报告”。两部分都要给用户可读内容，不要只输出其中一部分。
- 结构化判断摘要不是 JSON，不要用 Markdown 表格；使用 system prompt 中规定的固定字段名。
- 正式报告必须服从结构化判断摘要，不得在正式报告里新增与摘要冲突的动作建议。
- 如果上下文不足以给出动作，动作队列要明确写“今日可执行：无”，并说明原因。
- action_queue 里的“等待用户确认”必须覆盖所有 position_reviews 中需要用户确认的标的；不能摘要漏写、正文再补写。
- 触发条件必须来自该标的自身事实、研究信号、行情、财报、新闻或资产类型；不能套用其他行业的通用指标。

上下文 JSON：
```json
{{context_json}}
```
