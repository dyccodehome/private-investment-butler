# 私人投资管家技术文档

最后更新：2026-06-03

本文档记录当前项目已经实现的需求、工作流和核心技术设计。它用于后续继续开发、交接和复盘，不替代 `README.md` 的启动说明，也不替代 `requirements/ROADMAP.md` 的待办跟踪。

## 1. 目录结构

```text
private_investment_butler/
├── main.py                         # CLI 入口和主 Agent 管道
├── config.yaml                     # 非密钥配置：模型、框架、消息、调度、成本
├── requirements.txt                # Python 依赖
├── README.md                       # 使用说明和命令说明
├── ROADMAP.md                      # 指向 requirements/ROADMAP.md
├── docs/
│   └── TECHNICAL_OVERVIEW.md       # 本技术文档
├── frameworks/
│   ├── Cash_Anchor/
│   │   ├── constitution.md
│   │   ├── sub_frameworks/
│   │   ├── data/
│   │   ├── data_templates/
│   │   ├── chat_history/
│   │   ├── knowledge_inbox/
│   │   ├── patch_proposals/
│   │   └── patch_archive/
│   └── Growth_Engine/
│       ├── constitution.md
│       ├── sub_frameworks/
│       ├── data/
│       ├── data_templates/
│       ├── chat_history/
│       └── research_dossiers/
├── prompts/
│   ├── shared/
│   ├── worker/
│   ├── auditor/
│   ├── knowledge_absorber/
│   ├── absorb_discussion/
│   └── growth_review/
├── requirements/
│   ├── ROADMAP.md
│   ├── active/
│   ├── archive/
│   └── templates/
├── skills/
│   ├── portfolio_snapshot/
│   ├── research_dossier/
│   ├── trade_history/
│   ├── news-search/
│   ├── announcement-search/
│   └── hithink-market-query/
├── src/
│   ├── app_config.py
│   ├── command_registry.py
│   ├── master_router.py
│   ├── sub_agent.py
│   ├── skills.py
│   ├── llm_client.py
│   ├── auditor.py
│   ├── communication_gate.py
│   ├── feishu_long_connection.py
│   ├── feishu_runtime.py
│   ├── portfolio_ledger.py
│   ├── growth_portfolio.py
│   ├── longbridge_provider.py
│   ├── market_data/
│   ├── scheduler/
│   ├── knowledge_absorber.py
│   ├── absorb_discussion.py
│   ├── prompts.py
│   ├── context_logger.py
│   ├── trace_logger.py
│   ├── token_monitor.py
│   └── state.py
├── scripts/
│   ├── restart_feishu.sh
│   ├── run_growth_daily_review.py
│   ├── run_scheduler.py
│   └── token_report.py
├── runtime/
│   ├── traces/
│   ├── token_usage/
│   └── scheduler/
└── tests/
```

私有数据主要位于 `frameworks/*/data/`、`frameworks/*/chat_history/`、`frameworks/*/research_dossiers/`、`runtime/` 和 `.env`。这些内容应继续保持本地化，避免提交或进入镜像。

## 2. 已实现模块

### CLI 与 Slash Command

入口：`main.py`、`src/command_registry.py`

已实现命令：

```text
/help
/status
/usage
/frameworks
/contribute
/plan
/holding
/holdings
/buy
/sell
/dividend
/snapshot
/sync longbridge
/apply longbridge cash_anchor
/growth-holdings
/growth-watchlist
/growth-review
/growth-snapshot
/absorb
```

别名：

```text
/salary -> /contribute
/deposit -> /contribute
/target -> /plan
/position -> /holding
```

当前 `/plan` 只保留年度工资投入目标：

```text
/plan contribution=60000
```

系统已取消硬性的目标年分红。年复盘时只评估实际分红、收益率、回撤和框架执行质量。

### Cash Anchor 本地账本

入口：`src/portfolio_ledger.py`

已实现：

- 记录年度工资投入：`/contribute`
- 修改年度工资投入目标：`/plan`
- 单只红利持仓录入：`/holding <股票代码> <股数> <成本价>`
- 多只红利持仓批量录入：`/holdings`
- 买入、卖出、现金分红流水：`/buy`、`/sell`、`/dividend`
- 本地快照：`/snapshot`
- 分红和现价允许先缺省，分析前由只读行情 Provider 补充上下文。

关键原则：

- A 股个人持仓不依赖同花顺券商 API。
- 本地账本是持仓、成本、投入、分红流水的事实来源。
- Provider 查询结果用于分析上下文，不自动覆盖本地账本。

### Longbridge 美股只读同步

入口：`src/longbridge_provider.py`

已实现：

- 固定命令读取持仓：`longbridge positions --format json`
- 固定命令读取 quote：`longbridge quote <symbols> --format json`
- `/sync longbridge` 只生成同步提案，不写入账本。
- `/apply longbridge cash_anchor` 在明确命令下写入 Cash Anchor 子集。
- Cash Anchor 只接收 `QQQI`、`XQQI`、`TQQQ`，其它美股持仓过滤给 Growth 或其它策略。
- 保留已有分红字段和税率，不让同步覆盖本地审计轨迹。

### 统一市场数据 Provider

入口：`src/market_data/`

已实现：

- `symbol_mapper.py`：A 股、US symbol 规范化和 Provider symbol 映射。
- `yahoo_provider.py`：A 股通过 `yfinance` 查询最新价和分红信息。
- `longbridge_market_provider.py`：美股通过 Longbridge quote 查询。
- `provider_router.py`：按市场选择 Provider。
- `models.py`：统一返回结构。

统一返回结构：

```json
{
  "status": "ok | error",
  "source": "yfinance | longbridge",
  "market": "CN | US",
  "symbol": "600900.SH",
  "data": {},
  "error": ""
}
```

`hithink-market-query` 已通过 `src/skills.py` 接入统一 Provider。旧的财务、基本资料、选股、港股、期货、宏观和研报类 Skill 已删除；需要的核查顺序已合并进保留的行情、新闻、公告和研究档案 Skill。

### Growth Engine 本地持仓、自选和复盘

入口：`src/growth_portfolio.py`

已实现：

- Growth 持仓批量写入：`/growth-holdings`
- Growth 自选股批量写入：`/growth-watchlist`
- 单股复盘：`/growth-review <symbol>`
- 本地快照：`/growth-snapshot`
- 每日复盘脚本：`scripts/run_growth_daily_review.py`
- 复盘前自动附加 `market_data`：
  - A 股走 `yfinance`
  - 美股走 Longbridge

Growth 分为两个子框架：

- `CN_Alpha_Growth`
- `US_Disruptive_Growth`

### 知识吸收和宪法补丁

入口：`src/knowledge_absorber.py`、`src/absorb_discussion.py`

已实现：

- `/absorb <target_id> <source>` 生成宪法补丁提案。
- 支持总框架和子框架 target。
- 移除“观察池”，改为人工复核流程：
  - 继续讨论
  - 同意并打入宪法
  - 拒绝
- 讨论流程每轮调用 LLM，并传入：
  - 原始提案
  - 目标宪法
  - 审计意见
  - 完整讨论日志
  - 最新用户回复
- 用户已确认允许自动 `git commit`。

### 飞书长连接

入口：`src/feishu_long_connection.py`、`src/feishu_runtime.py`、`src/communication_gate.py`

已实现：

- 使用飞书长连接，不需要公网 webhook URL。
- 支持普通文本消息。
- 支持交互卡片回调。
- 支持知识吸收审批按钮。
- 支持审计拒绝后的人工操作按钮。
- 支持 `FEISHU_DEFAULT_CHAT_ID` 主动推送。
- `scripts/restart_feishu.sh` 用于重启飞书应用。

### Scheduler 定时复盘

入口：`src/scheduler/`、`scripts/run_scheduler.py`

已实现：

- 本机常驻方式。
- 当前已开启一周试用：
  - `scheduler.enabled=true`
  - `dry_run_by_default=false`
- A 股每日复盘：北京时间 16:30
- 美股每日复盘：北京时间 06:00
- 周复盘：周日 20:00
- 每日任务跳过周末。
- 节假日通过 `config.yaml` 手工维护。
- 失败写入 `runtime/scheduler/runs.jsonl`，并可向默认飞书会话推送错误摘要。

启动：

```bash
python3 scripts/run_scheduler.py --run-loop
```

### Prompt 集中管理

入口：`prompts/`、`src/prompts.py`

已实现：

- Python 层只负责模板加载和变量渲染。
- Prompt 正文集中在 `prompts/`。
- 支持 Worker、Auditor、Knowledge Absorber、Absorb Discussion、Growth Review。

### 观测、日志和成本

入口：

- `src/context_logger.py`
- `src/decision_record.py`
- `src/trace_logger.py`
- `src/token_monitor.py`
- `src/budget_manager.py`
- `src/cost_meter.py`
- `src/observability_api.py`

已实现：

- 每轮 Agent 状态写入策略岛 `chat_history`。
- 每轮终态输出写入 `runtime/decisions/YYYY-MM-DD.jsonl`，形成投资审计记录。
- 全链路 trace 写入 `runtime/traces/YYYY-MM-DD.jsonl`。
- LLM token usage 写入 `runtime/token_usage/YYYY-MM-DD.jsonl`。
- Prompt 使用 hash 指纹记录，避免直接存 prompt 原文。
- 支持按阈值提醒 token 用量。
- workflow token budget 写入 trace，超过 warn/max 时增加风险标记。

### Harness Runtime 和工具治理

入口：

- `src/harness_runtime.py`
- `configs/tool_registry.yaml`
- `src/tool_registry.py`
- `src/action_card.py`

已实现：

- `HarnessRuntime` 作为当前 `main.py::run_pipeline()` 的稳定 facade，方便后续迁移主流程。
- Tool Registry 记录工具风险等级、访问类型、允许策略岛、允许 Agent、是否需要人工确认和输出 schema。
- `skills.load_skill()` 在披露数据前校验 Tool Registry，并把 Skill 输出统一为 `{status, source, data_type, data, freshness, warnings, error}`。
- `ActionCard` 提供标准执行卡片格式基础，后续用于高风险 WARN/REJECT 和 Growth Review 输出。

## 3. Agent 调用链

主流程在 `main.py::run_pipeline()`。

标准自然语言调用链：

```text
用户输入
  -> main.py
  -> command_registry.handle_command()
      -> 如果是 Slash Command，直接执行确定性命令并返回
      -> 如果不是命令，进入 Agent Pipeline
  -> AgentState 初始化
  -> trace_state_event(message_received)
  -> master_router.route_intent()
  -> trace_state_event(route_decision)
  -> communication_gate.send(路由结果)
  -> sub_agent.intake_precheck()
      -> 不适合则 BOUNCED，最多重试 config.yaml::router.max_route_retries
  -> sub_agent.stage_one_request_skills()
      -> 子 Agent 只申请 Skill，不直接取数据
  -> main.py 调用 skills.load_skill()
  -> DisclosureRecord 写入 AgentState
  -> sub_agent.stage_two_decide()
      -> LLM Worker 生成决策草案
  -> auditor.audit_before_output()
      -> 独立 Auditor LLM 审计
      -> 审计路径会额外加载 news-search 反方证据
  -> auditor.enforce_circuit_breaker()
      -> PASS/WARN：输出最终答案
      -> REJECT：发送人工确认卡片
  -> communication_gate.send() 或 send_card()
  -> context_logger.save_chat_session()
  -> trace_state_event(chat_session_saved)
```

Slash Command 调用链：

```text
用户输入 /xxx
  -> main.py
  -> command_registry.handle_command()
  -> 对应确定性 handler
  -> 本地文件读写或 Provider 调用
  -> 返回文本
```

飞书长连接调用链：

```text
飞书事件
  -> feishu_long_connection
  -> feishu_runtime
  -> command_registry 或 run_pipeline
  -> communication_gate
  -> 飞书消息/卡片
```

知识吸收调用链：

```text
/absorb target_id source
  -> knowledge_absorber
  -> LLM 生成 patch proposal
  -> Auditor 审计
  -> Feishu 卡片
      -> 继续讨论：absorb_discussion 调 LLM 更新提案
      -> 同意：accept_patch_proposal() 打入宪法并 git commit
      -> 拒绝：归档/结束
```

Scheduler 调用链：

```text
scripts/run_scheduler.py --run-loop
  -> scheduler.config.load_scheduler_config()
  -> scheduler.runner.due_jobs()
  -> scheduler.runner.run_job_once()
  -> scheduler.jobs.run_growth_daily_review_job()
  -> growth_portfolio.review_growth_daily()
  -> LLM Growth Reviewer
  -> communication_gate.send(default_chat_id)
  -> runtime/scheduler/runs.jsonl
```

## 4. 数据结构

### AgentState

定义：`src/state.py`

核心字段：

```text
user_input
chat_id
trace_id
framework_id
context_bundle_id
loaded_context_files
route_reason
route_attempts
bounce_reason
requested_skills
disclosed_data
worker_notes
draft_decision
audit_persona
audit_log
audit_signal
final_answer
user_action
status
errors
```

状态枚举：

```text
RUNNING
NEEDS_DISCLOSURE
BOUNCED
AUDIT_REJECTED
COMPLETED
FAILED
```

### SkillRequest

```json
{
  "skill_name": "portfolio_snapshot",
  "reason": "需要读取 Cash Anchor 本地持仓...",
  "arguments": {}
}
```

### DisclosureRecord

```json
{
  "skill_name": "portfolio_snapshot",
  "arguments": {},
  "payload": {}
}
```

### DebateEntry

```json
{
  "role": "auditor",
  "content": "[ALLOW] ...",
  "verdict": "PASS"
}
```

### Cash Anchor 数据

`frameworks/Cash_Anchor/data/holdings.csv`

```text
symbol
name
market
currency
shares
cost_price
current_price
annual_dividend_per_share
tax_rate
notes
```

`capital_flows.csv`

```text
date
amount
currency
source
notes
```

`portfolio_events.csv`

```text
date
event_type
symbol
shares
price
amount
currency
source
notes
```

`dividend_plan.yaml`

```yaml
plan_name: Cash Anchor 10 Year Retirement Plan
base_year: 2026
retirement_years: 10
annual_contribution_target: 60000
currency: CNY
```

注意：已取消 `target_annual_dividend`。

Cash Anchor snapshot summary：

```json
{
  "holding_count": 0,
  "total_cost": 0,
  "total_market_value": 0,
  "gross_annual_dividend": 0,
  "net_annual_dividend": 0,
  "yield_on_cost": 0,
  "current_yield": 0,
  "net_yield_on_cost": 0,
  "current_year_contribution": 0,
  "annual_contribution_progress": 0,
  "annual_contribution_gap": 0
}
```

增强快照会额外附带：

```json
{
  "market_data": {
    "600900.SH": {
      "status": "ok",
      "source": "yfinance",
      "market": "CN",
      "symbol": "600900.SH",
      "data": {},
      "error": ""
    }
  },
  "market_data_policy": {
    "source_rule": "CN uses yfinance; US uses Longbridge.",
    "failure_policy": "If status is error, treat current quote/dividend as missing and state the data gap.",
    "write_policy": "Read-only during analysis; do not overwrite holdings.csv automatically."
  }
}
```

### Growth Engine 数据

`growth_holdings.csv`

```text
symbol
name
market
sub_framework
shares
cost_price
current_price
position_type
thesis
status
last_review_at
notes
```

`growth_watchlist.csv`

```text
symbol
name
market
sub_framework
priority
watch_reason
trigger_condition
status
last_review_at
notes
```

Growth snapshot summary：

```json
{
  "holding_count": 0,
  "watchlist_count": 0,
  "total_cost": 0,
  "total_market_value": 0,
  "unrealized_pnl": 0,
  "unrealized_pnl_pct": 0,
  "by_market": {},
  "by_sub_framework": {}
}
```

复盘前增强字段：

```json
{
  "market_data": {},
  "market_data_policy": {
    "source_rule": "CN uses yfinance; US uses Longbridge.",
    "failure_policy": "If status is error, treat current quote/dividend as missing and state the data gap."
  }
}
```

### MarketDataResult

定义：`src/market_data/models.py`

```json
{
  "status": "ok | error",
  "source": "yfinance | longbridge",
  "market": "CN | US",
  "symbol": "string",
  "data": {},
  "error": ""
}
```

### Scheduler 配置

`config.yaml`

```yaml
scheduler:
  enabled: true
  timezone: Asia/Shanghai
  dry_run_by_default: false
  skip_weekends_for_daily: true
  skip_holidays: true
  holidays:
    CN: []
    US: []
  jobs:
    growth_cn_daily_review:
      enabled: true
      type: growth_daily_review
      market: CN
      schedule: daily
      time: "16:30"
    growth_us_daily_review:
      enabled: true
      type: growth_daily_review
      market: US
      schedule: daily
      time: "06:00"
    growth_weekly_review:
      enabled: true
      type: growth_weekly_review
      market: ALL
      schedule: weekly
      weekday: sunday
      time: "20:00"
```

## 5. Prompt 设计

Prompt 正文集中在 `prompts/`，入口函数在 `src/prompts.py`。

### 共享响应风格

文件：`prompts/shared/response_style.md`

用途：

- 统一措辞。
- 避免夸张修饰。
- 让 Agent 回复简洁、准确、可执行。

### Worker Prompt

文件：

```text
prompts/worker/system.md
prompts/worker/user.md
```

输入变量：

```text
framework_id
context_bundle_id
loaded_context_files
strategy_context
user_input
disclosed_data_names
disclosed_data
response_style
```

设计目标：

- Worker 只看到当前策略岛宪法和被披露的数据。
- Worker 不直接调用工具。
- Worker 必须用 If-Then 逻辑输出可审计决策。

### Auditor Prompt

文件：

```text
prompts/auditor/system_base.md
prompts/auditor/system_risk.md
prompts/auditor/system_purist.md
prompts/auditor/system_neutral.md
prompts/auditor/user.md
```

审计 persona：

- 风险审计：拦截买入、加仓、建仓等动作。
- 规则变更审计：拦截知识吸收、宪法补丁、框架修改。
- 流程审计：默认审计。

输出信号：

```text
[ALLOW] / PASS
[WARN] / WARN
[REJECT] / REJECT
[HUMAN_REVIEW] / REJECT
```

### Knowledge Absorber Prompt

文件：

```text
prompts/knowledge_absorber/system.md
prompts/knowledge_absorber/user.md
```

用途：

- 将碎片知识转成宪法 patch proposal。
- 输出目标文件、目标段落、替换内容、风险说明。

### Absorb Discussion Prompt

文件：

```text
prompts/absorb_discussion/system.md
prompts/absorb_discussion/user.md
```

用途：

- 在用户点“继续讨论”后，把完整讨论上下文交给 LLM。
- 多轮调整 patch proposal。
- 最终仍由用户同意或拒绝。

### Growth Review Prompt

文件：

```text
prompts/growth_review/system.md
prompts/growth_review/user.md
```

用途：

- 单股复盘。
- 市场每日复盘。
- 周复盘。
- 输入包含本地 Growth snapshot 和只读市场数据。

## 6. Rule Engine 设计

当前项目没有单独命名为 `rule_engine.py` 的模块，但规则引擎由多个确定性边界组成。

### 语义路由规则

文件：`src/master_router.py`

规则：

- 命中红利、股息、分红、期权、现金流等关键词：`Cash_Anchor`
- 命中 A 股成长、科技自立、半导体、新能源等关键词：`Growth_Engine`
- 命中美股、AI、SaaS、生物科技、颠覆性成长等关键词：`Growth_Engine`
- 语义不足时默认进入 `Cash_Anchor` 预检。

### 子框架选择规则

文件：`src/sub_agent.py`

Cash Anchor：

- `CN_Dividend_Income`
- `US_Income_Options`

Growth Engine：

- `CN_Alpha_Growth`
- `US_Disruptive_Growth`

选择方式：

- 对用户输入进行关键词计分。
- 得分最高且大于 0 的子框架被加载。
- 否则只加载总框架。

### 接单预检和弹回

文件：`src/sub_agent.py`

规则：

- 被选中的 framework 必须命中自身关键词。
- 不匹配则 `PipelineStatus.BOUNCED`。
- 主流程最多重试 `config.yaml::router.max_route_retries`。

当前状态：路由重试次数已从 `config.yaml` 读取，默认值为 3。

### Skill 渐进披露规则

文件：`src/sub_agent.py`、`src/skills.py`

规则：

- Worker 先申请 Skill。
- 只有主流程能调用 Skill。
- 调用结果以 `DisclosureRecord` 写回 `AgentState`。
- Worker 第二阶段只能看到披露数据。

Cash Anchor 账本触发关键词：

```text
持仓、成本、成本价、股息率、分红、红利、退休、工资、投入、追加、本金、进度、年度目标、现金流目标、今年会分多少
```

### 审计 persona 选择规则

文件：`src/auditor.py`

规则：

- 命中买入、加仓、补仓、建仓等词：风险审计。
- 命中 `/absorb`、宪法、补丁、知识吸收等词：规则变更审计。
- 其它：流程审计。

### Circuit Breaker

文件：`src/auditor.py`

规则：

- `REJECT` 或 `HUMAN_REVIEW`：暂停自动输出，发送人工确认卡片。
- `WARN`：允许输出，但保留审计记录。
- `PASS`：正常输出。

### 外部命令白名单

文件：`src/longbridge_provider.py`

只允许：

```text
longbridge positions --format json
longbridge quote <symbols> --format json
```

LLM 不允许自由拼接 shell 命令。

### Scheduler 规则

文件：`src/scheduler/config.py`

规则：

- job 必须启用。
- 当天同一 job 只能运行一次。
- 未到配置时间不运行。
- daily job 可跳过周末。
- holiday 列表命中则跳过。
- weekly job 需要匹配 weekday。

## 7. 日志 schema

### Trace 日志

路径：

```text
runtime/traces/YYYY-MM-DD.jsonl
```

写入：`src/trace_logger.py`

Schema：

```json
{
  "timestamp": "2026-06-03 12:00:00",
  "trace_id": "trace_xxx",
  "span_id": "span_xxx",
  "parent_span_id": null,
  "chat_id": "cli",
  "framework_id": "Cash_Anchor",
  "agent_role": "worker",
  "event_type": "draft_decision_created",
  "status": "success",
  "latency_ms": 123,
  "input_preview": "用户输入摘要",
  "output_preview": "输出摘要",
  "token_usage": {},
  "risk_flags": [],
  "metadata": {},
  "error": ""
}
```

常见 `event_type`：

```text
message_received
route_decision
route_bounce
skill_requested
skill_disclosed
draft_decision_created
audit_started
audit_finished
circuit_breaker_triggered
final_message_sent
chat_session_saved
pipeline_failed
llm_call_finished
```

### Chat History

路径：

```text
frameworks/{framework_id}/chat_history/YYYY-MM-DD.jsonl
```

写入：`src/context_logger.py`

Schema：

```json
{
  "timestamp": "2026-06-03 12:00:00",
  "trace_id": "trace_xxx",
  "chat_id": "cli",
  "framework_id": "Cash_Anchor",
  "context_bundle_id": "CN_Dividend_Income",
  "loaded_context_files": [],
  "route_reason": "识别到现金流防守语义",
  "route_attempts": 1,
  "user_query": "红利持仓今年分红怎么看",
  "disclosed_data": [],
  "agent_proposal": "Worker 草案",
  "auditor_critique": [],
  "audit_persona": "风险审计",
  "audit_signal": "PASS",
  "final_reply_to_user": "最终回复",
  "user_action": null,
  "worker_notes": [],
  "errors": [],
  "status": "completed"
}
```

### Token Usage

路径：

```text
runtime/token_usage/YYYY-MM-DD.jsonl
```

写入：`src/token_monitor.py`

Schema：

```json
{
  "timestamp": "2026-06-03 12:00:00",
  "trace_id": "trace_xxx",
  "provider": "deepseek",
  "model": "deepseek-v4-pro",
  "agent_role": "worker",
  "call_site": "sub_agent.stage_two_decide",
  "framework_id": "Cash_Anchor",
  "context_bundle_id": "CN_Dividend_Income",
  "chat_id": "cli",
  "user_query": "用户问题",
  "input_tokens": 0,
  "output_tokens": 0,
  "reasoning_tokens": 0,
  "total_tokens": 0,
  "estimated_cost_usd": 0,
  "latency_ms": 0,
  "status": "success | error | not_configured",
  "error": "",
  "prompt_fingerprint": "sha256-prefix"
}
```

### Scheduler Run Log

路径：

```text
runtime/scheduler/runs.jsonl
```

写入：`src/scheduler/runner.py`

Schema：

```json
{
  "run_key": "2026-06-03:growth_cn_daily_review",
  "job": "growth_cn_daily_review",
  "job_type": "growth_daily_review",
  "market": "CN",
  "status": "ok | error",
  "dry_run": false,
  "error": "",
  "result_preview": "前 500 字",
  "created_at": "2026-06-03T16:30:00+08:00"
}
```

### Research Dossier

路径：

```text
frameworks/Growth_Engine/research_dossiers/
```

当前已经有 `research_dossier` 相关读取/追加入口，但闭环仍未完全完成。后续应把最终结论、审计拒绝、人工覆盖都稳定写入对应 dossier。

## 8. 技术选型

### 语言和运行方式

- Python 3
- 本地优先
- 纯 Python 手写 Agent 管道
- 不使用 LangGraph 等重型状态机框架

原因：

- 当前流程规模可控。
- 透明可审计。
- 每个节点的状态转换都能在 `AgentState` 中追踪。
- 易于本地长期运行和调试。

### LLM Provider

入口：`src/llm_client.py`

支持：

- OpenAI Responses API
- DeepSeek Chat Completions
- Gemini generateContent

当前默认 provider 是 `deepseek`，默认模型是 `deepseek-v4-pro`；OpenAI 和 Gemini 作为可选 provider 保留。

配置来自：

```text
config.yaml
.env
```

Worker、Auditor、Knowledge Absorber 可以使用不同 provider/model/reasoning 配置。

### 通讯

- 飞书长连接
- 不使用公网 webhook
- `lark-oapi`
- 消息和卡片统一经 `communication_gate`

### 数据存储

- 本地 CSV：持仓、流水、事件
- 本地 YAML：年度投入计划
- 本地 JSONL：trace、token、chat history、scheduler runs
- 无数据库

原因：

- 私人投资数据更适合本地化。
- 文件容易人工检查、备份、回滚。
- 当前规模不需要数据库。

### 金融数据源

- A 股：Yahoo Finance / `yfinance`
- 美股：Longbridge CLI quote/positions
- 新闻、公告、研报：暂未完成统一迁移

原则：

- LLM 不直接调用外部 API 或 shell。
- 外部数据必须经过固定 Python Provider。
- 交易能力默认不开放。

### 定时任务

- 轻量 Python loop
- 不先引入 APScheduler
- 本机常驻

原因：

- 任务数量少。
- 便于测试。
- 当前不需要分布式调度。

### 测试

当前全量单元测试已覆盖：

- 命令注册和命令行为
- Cash Anchor 账本
- Longbridge Provider
- Market Data Provider
- Growth 复盘
- Prompt loader
- Scheduler
- 飞书 runtime
- 知识吸收讨论
- 路由和上下文选择

最近验证结果：`python3 -m unittest discover -v` 通过 70 个测试。

## 9. 当前痛点和下一步改造路径

### 痛点 1：路由和预检仍偏关键词

现状：

- `master_router.py` 和 `sub_agent.py` 使用关键词规则。
- 透明、稳定，但对复杂自然语言理解有限。

改造路径：

1. 增加更多中英文市场词别名。
2. 为常见误路由写测试。
3. 在确定性规则稳定后，加入可选 LLM router，但保留关键词 fallback。

### 痛点 2：Skill 返回结构还未完全统一

现状：

- Market Data Provider 已统一 `{status, source, market, symbol, data, error}`。
- `trade_history`、`news-search`、`announcement-search`、`hithink-market-query` 已返回结构化 payload。
- `portfolio_snapshot` 和 `research_dossier` 仍保留业务快照结构，后续可继续收敛到统一 status schema。

改造路径：

1. 为 `portfolio_snapshot`、`research_dossier` 统一 status schema。
2. 缺少凭据时返回 `not_configured` 或明确错误，而不是空数据。
3. 在 Worker prompt 中明确区分 `ok/error/missing`。

### 痛点 3：公告、研报数据还未统一迁移

现状：

- 行情 Provider 已迁移到 yfinance/Longbridge。
- `news-search` 已接入同花顺问财新闻搜索 payload；缺少 `IWENCAI_API_KEY` 时返回 `not_configured`。
- 公告、研报仍处于旧 Skill 或未完全真实执行状态。

改造路径：

1. 实现公告/研报 Provider。
2. 把新闻、公告和研报纳入 Growth 每日复盘。
3. 对数据新鲜度增加 `freshness` 字段。

### 痛点 4：A 股持仓对账流程未实现

现状：

- A 股以本地账本为主。
- 用户可以用 `/holding`、`/holdings`、`/buy`、`/sell`、`/dividend` 维护。
- 还没有 `/reconcile A`。

改造路径：

1. 新增 `/reconcile A`。
2. 支持手工输入或截图/导出表对账。
3. 记录最近对账日期。
4. 超过 30 天未对账时，在分析里提示账本可能过期。

### 痛点 5：研究档案闭环未完全完成

现状：

- 已有 `research_dossier` 模块。
- `context_logger` 尝试追加决策到 dossier。
- 但最终结论、审计拒绝、人工覆盖的闭环还不完整。

改造路径：

1. 主流程终态统一调用 dossier append。
2. 记录 PASS/WARN/REJECT 和人工覆盖。
3. 财报、新闻后可触发 dossier refresh。
4. 输出中提示 dossier stale 状态。

### 痛点 6：Scheduler 已启用，但生产运行方式仍需要观察

现状：

- 本机常驻一周试用。
- 依赖本机进程持续运行。
- 失败日志可写入 runtime。

改造路径：

1. 一周后复盘任务触发是否稳定。
2. 增加进程健康检查。
3. 需要时再做 launchd、systemd 或 Docker。
4. 节假日列表从手工配置升级为交易日历。

### 痛点 7：飞书生产流程还需要完整验收

现状：

- 长连接、消息、卡片回调已经实现。
- 仍需要完整生产 smoke test。

改造路径：

1. 测普通消息。
2. 测 Slash Command。
3. 测重复事件抑制。
4. 测 chat_id 锁。
5. 测知识吸收审批按钮。
6. 测审计拒绝后 `force_execute` / `abandon_operation`。

### 痛点 8：本地文件越来越多，缺少统一数据迁移机制

现状：

- 已从 `dividend_plan.yaml` 删除 `target_annual_dividend`。
- 读取旧字段时目前会忽略。
- 未来 schema 变更可能增多。

改造路径：

1. 增加 `scripts/migrate_data.py`。
2. 对 CSV/YAML schema 增加 version。
3. 每次结构变更写 migration。
4. migration 执行前备份私有数据。

### 痛点 9：观测面板还未成为日常工具

现状：

- trace 和 token JSONL 已有。
- `observability_api.py` 和 dashboard 存在。
- README 还未完整说明观测面板的非 webhook 启动方式。

改造路径：

1. README 增加观测面板启动命令。
2. 增加失败 trace 聚合视图。
3. 增加最贵 LLM 调用视图。
4. 增加审计拒绝和人工覆盖统计。

## 当前建议优先级

1. 完成飞书生产 smoke test。
2. 一周后复盘 Scheduler 稳定性。
3. 实现 `/reconcile A`，补齐 A 股本地账本可信度。
4. 统一所有 Skill payload schema。
5. 完成研究档案闭环。
6. 接入新闻、公告、研报 Provider。
