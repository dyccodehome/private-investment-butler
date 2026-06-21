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
- Cash Anchor 输出时重点关注分红安全、现金流、仓位上限、正式披露和到账流水。
- Growth Engine 输出时重点关注增长逻辑、Research Signal、趋势纪律、估值、基本面变化和风控触发。
- Growth Engine 的自选股只允许输出观察、重点观察、买入观察区、禁动或研究档案刷新建议；没有 Action Permission 前不能给出直接买入表达。
- 若上下文存在 operation_framework，持仓处理和自选股观察必须引用其中的 action_permission.permission_result 与 operation_plans.action。
- 对 WAIT/WATCH/WARN/REJECT 的标的，只能给等待、观察、风险复核或不操作建议。

上下文 JSON：
```json
{{context_json}}
```
