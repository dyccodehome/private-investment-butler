# Harnessed Investment Agent OS

本文档记录目标架构和当前落地方式。`docs/TECHNICAL_OVERVIEW.md` 说明“现在怎么实现”，本文说明“为什么这样分层，以及下一步如何演进”。

## 1. Project Positioning

Private Investment Butler 是一个本地优先、规则缰绳驱动的个人投资 Agent Runtime。

它的核心不是让 LLM 直接生成投资建议，而是把 LLM 放进一套受控 Harness：

```text
本地账本事实源
  + 投资宪法
  + Tool Registry
  + 渐进披露
  + Worker 决策
  + Auditor / Devil's Advocate
  + Circuit Breaker
  + 飞书人工确认
  + Trace
  + Decision Record
  + Token Budget
  + Knowledge Absorption
  + Rule Evolution
```

## 2. Harness Runtime

当前主流程仍在 `main.py::run_pipeline()`，`src/harness_runtime.py` 提供稳定的 Runtime facade。

Harness Runtime 的职责：

- 初始化 `AgentState`
- 路由到唯一策略岛
- 执行 Worker 接单预检
- 审批 SkillRequest
- 按 Tool Registry 披露数据
- 调用 Worker LLM 生成草案
- 调用 Auditor LLM 做反方审计
- 执行 Circuit Breaker
- 发送飞书或 CLI 输出
- 写入 Trace、Decision Record、Chat History

## 3. Constitution Layer

策略岛位于 `frameworks/`：

- `Cash_Anchor`
- `Growth_Engine`

每个 Worker 只读取当前策略岛的 `constitution.md` 和必要子框架文件，不跨岛读取规则。

## 4. Tool Governance Layer

Tool Registry 位于：

```text
configs/tool_registry.yaml
src/tool_registry.py
```

原则：

- Agent 不直接调用工具。
- Agent 只能提交 `SkillRequest`。
- Harness Runtime 根据 Tool Registry 判断是否允许披露。
- Registry 记录 `risk_level`、`access_type`、`allowed_frameworks`、`allowed_agents`、`requires_human_approval`、`output_schema`。
- 所有 Skill payload 必须被标准化为统一 schema。

## 5. Standard Skill Payload

所有 Skill 对 Worker/Auditor 披露前都会被包成：

```json
{
  "status": "ok | error | missing | empty | provider_not_configured | unauthorized",
  "source": "local | yfinance | longbridge | market_intel_news | market_intel_announcements | external",
  "data_type": "portfolio_snapshot | market_data | news | research_dossier | trade_history",
  "data": {},
  "freshness": {
    "as_of": "2026-06-03T16:30:00",
    "stale": false,
    "stale_reason": ""
  },
  "warnings": [],
  "error": ""
}
```

这保证模型能区分数据正常、缺失、过期、未配置和无权限，不用编造事实填空。

## 6. Audit Gate

`src/auditor.py` 是当前 Audit Gate。

审计 persona：

- 风险审计：买入、加仓、补仓等动作触发。
- 规则变更审计：`/absorb` 或规则修改触发。
- 流程审计：普通输出触发。

下一步目标是把 Auditor 升级为更结构化的 Devil's Advocate：

- 明确 `main_objections`
- 明确 `missing_evidence`
- 明确 `violated_rules`
- 给出 `recommended_revision`
- 对高风险建议输出 `must_block`

## 7. Decision Record

Trace 是工程链路；Decision Record 是投资审计记录。

当前写入：

```text
runtime/decisions/YYYY-MM-DD.jsonl
```

每条记录包含：

- `decision_id`
- `trace_id`
- `framework_id`
- `context_bundle_id`
- `decision_type`
- `skill_disclosures`
- `draft_decision`
- `audit_persona`
- `audit_signal`
- `circuit_breaker`
- `final_answer`
- `requires_human_approval`
- `user_action`

Decision Record 用于周末复盘、人工覆盖审计、策略质量评估和未来 Agent Eval。

## 8. Budget Manager

Token usage 是事后账本，Budget Manager 是运行时预算信号。

配置位于：

```text
config.yaml::budgets
src/budget_manager.py
```

当前能力：

- workflow 启动时写入 `budget_started` trace
- 每次 LLM 调用后累计当前 trace token
- 达到 `warn_tokens` 写 `budget_warned`
- 达到 `max_tokens` 写 `budget_exceeded`

下一步可增加降级策略：压缩上下文、跳过低价值复盘、只输出异常标的、保留审计但缩短讨论轮次。

## 9. Rule Evolution

`/absorb` 是规则进化入口。

当前流程：

```text
外部知识
  -> Patch Proposal
  -> 审计
  -> 飞书审批
  -> 继续讨论 / 同意 / 拒绝
  -> constitution 精确替换
  -> git commit
```

下一步增加 Insight Classification：

```text
外部观点
  -> insight extraction
  -> insight classification
  -> constitution_patch | research_dossier_only | watch_metric | risk_warning | reject
```

## 10. Action Card

`src/action_card.py` 提供标准 Action Card 格式。

目标是把高风险输出从长篇分析收敛为：

- 结论
- 当前状态
- 允许动作
- 禁止动作
- 触发规则
- 反方审计
- 后续动作

当前只是格式基础，后续会接入 Auditor WARN/REJECT 和 Growth Review。

## 11. Eval Pipeline

工程测试位于 `tests/`。

下一步建议新增 Agent 质量 eval：

```text
tests/evals/
├── cases/
└── test_agent_eval.py
```

重点检查：

- 是否触发正确 auditor
- 是否识别禁止动作
- 是否没有编造数据
- 是否写入 Decision Record
- 是否生成 Action Card
- 是否保留 Trace

## 12. Roadmap Summary

优先级：

1. 飞书生产 smoke test
2. Tool Registry 和 Skill payload 完整收敛
3. Decision Record 日常复盘
4. Research Dossier 闭环
5. Insight Classification
6. Action Card 接入高风险输出
7. Budget Manager 降级策略
8. Agent Eval Pipeline
