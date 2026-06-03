# Private Investment Butler

A local-first multi-agent investment assistant built with pure Python orchestration.

This project is a personal AI application engineering showcase: it demonstrates a hand-rolled agent pipeline for investment reasoning, strategy isolation, progressive disclosure, AOP-style audit, Feishu communication, local conversation logging, and token usage monitoring.

> This repository contains code and public-safe scaffolding only. Personal investment logs, chat history, runtime token ledgers, and credentials are intentionally excluded from Git.

## Highlights

- **Hand-rolled orchestration**: no LangGraph or heavy state-machine framework.
- **Strategy-isolated workers**: each strategy has its own `constitution.md` and private log space.
- **Progressive Skill disclosure**: Skills are loaded only when requested by a worker.
- **AOP audit middleware**: an independent auditor challenges worker decisions before output.
- **Feishu long connection**: receives messages and card callbacks through the Feishu SDK WebSocket connection, without a public callback URL.
- **Human-in-the-loop circuit breaker**: rejected decisions can be resolved through interactive callbacks.
- **Local black-box logging**: each strategy records private chat history as local JSONL.
- **Token usage ledger**: model usage is recorded by role, framework, call site, and prompt fingerprint.
- **Configurable LLM providers**: current default uses DeepSeek Chat Completions; OpenAI Responses API and Gemini are also supported.

## 代码结构

```text
private_investment_butler/
├── AGENTS.md                     # Agent 设计说明
├── config.yaml                   # 非密钥运行配置
├── configs/                      # Tool Registry 等治理配置
├── main.py                       # CLI 与主流程入口
├── frameworks/                   # 策略框架与本地数据
│   ├── Cash_Anchor/
│   └── Growth_Engine/
├── prompts/                      # LLM system/user prompt 模板
├── requirements/                 # 用户需求文档和讨论留档
├── skills/                       # 按需加载的 Skill 说明和工具边界
├── src/                          # 核心 Python 模块
├── scripts/                      # 本地脚本和人工启动工具
└── runtime/                      # 本地运行日志，默认不入库
```

### 文件职责分类

| 分类 | 文件 | 职责 |
| --- | --- | --- |
| 入口 | `main.py` | CLI 输入、运行模式分发、主流程启动 |
| 命令层 | `src/command_registry.py` | Slash command 注册、解析、帮助文案和命令分发 |
| 飞书接入 | `src/feishu_long_connection.py`, `src/feishu_runtime.py`, `src/communication_gate.py` | 长连接、事件处理、消息和交互卡片发送 |
| 路由与执行 | `src/harness_runtime.py`, `src/master_router.py`, `src/sub_agent.py`, `src/skills.py` | Harness Runtime facade、语义路由、策略上下文选择、Skill 加载 |
| 工具治理 | `configs/tool_registry.yaml`, `src/tool_registry.py` | Tool Registry、框架/Agent 权限、风险等级和 Skill payload 校验 |
| Prompt 模板 | `prompts/`, `src/prompts.py` | 集中管理 system/user prompt 正文，Python 层只负责加载和变量渲染 |
| 需求文档 | `requirements/` | 保存用户需求、讨论结论、验收标准和实现记录 |
| LLM 与审计 | `src/llm_client.py`, `src/auditor.py` | 模型调用和审计关 |
| 知识吸收 | `src/knowledge_absorber.py`, `src/absorb_discussion.py` | 宪法补丁生成、继续讨论、同意或拒绝 |
| 现金流账本 | `src/portfolio_ledger.py`, `src/longbridge_provider.py` | Cash Anchor 本地账本、长桥只读同步 |
| 成长股账本 | `src/growth_portfolio.py` | Growth Engine 本地持仓、自选股、单股和每日复盘 |
| 定时任务 | `src/scheduler/`, `scripts/run_scheduler.py` | 读取 `config.yaml`，按时间匹配复盘任务，默认只干跑 |
| 观测与日志 | `src/context_logger.py`, `src/decision_record.py`, `src/token_monitor.py`, `src/budget_manager.py`, `src/trace_logger.py`, `src/observability_api.py` | 对话日志、Decision Record、Token 统计、预算检查、运行 trace、观测面板接口 |
| 通用支撑 | `src/app_config.py`, `src/file_io.py`, `src/init.py`, `src/state.py`, `src/session_lock.py`, `src/error_classifier.py`, `src/cost_meter.py` | 配置、文件读写、路径初始化、状态、并发保护和错误分类 |
| 脚本 | `scripts/restart_feishu.sh`, `scripts/run_growth_daily_review.py`, `scripts/run_scheduler.py`, `scripts/token_report.py` | 重启飞书应用、成长股单次复盘、Scheduler 干跑或常驻、Token 报告 |
| 测试 | `tests/` | 命令、飞书、知识吸收、账本、路由和上下文测试 |

## Strategy Islands

- `Cash_Anchor`: defensive cash-flow anchor for dividends, option premium, and portfolio liquidity.
- `Growth_Engine`: offensive growth engine with A-share growth and US disruptive growth sub-frameworks.

Each strategy owns:

```text
constitution.md
logs/
chat_history/
```

Only `.gitkeep` files are committed under `logs/` and `chat_history/`. Real local records are ignored.

## Core Pipeline

The main lifecycle lives in `main.py`:

1. Semantic routing by `src/master_router.py`
2. Worker intake precheck by `src/sub_agent.py`
3. On-demand Skill loading by `src/skills.py`
4. Worker reasoning through `src/llm_client.py`
5. AOP audit by `src/auditor.py`
6. Feishu/user output through `src/communication_gate.py`
7. Decision audit logging by `src/decision_record.py`
8. Local black-box logging by `src/context_logger.py`
9. Token usage and workflow budget checks by `src/token_monitor.py` and `src/budget_manager.py`

## Configuration

Copy the environment template:

```bash
cp .env.example .env
```

Configure credentials locally:

```bash
OPENAI_API_KEY=...
FEISHU_APP_ID=...
FEISHU_APP_SECRET=...
FEISHU_VERIFICATION_TOKEN=...
FEISHU_ENCRYPT_KEY=...
FEISHU_DEFAULT_CHAT_ID=...
YUQUE_TOKEN=...
IWENCAI_API_KEY=...
```

Do not commit `.env`.

## Run Locally

```bash
python3 -m compileall .
printf 'A股半导体成长股跌破MA120要不要撤\n' | python3 main.py
```

Run Feishu long connection mode:

```bash
./scripts/restart_feishu.sh
```

Long connection mode is the preferred local-first mode. It does not require a public callback URL; the app uses `FEISHU_APP_ID` and `FEISHU_APP_SECRET` to receive subscribed Feishu events and card callbacks through the Feishu SDK WebSocket connection.

## Commands

Commands work in both CLI and Feishu messages.

Show available commands:

```bash
printf '/help\n' | python3 main.py
```

### Cash Anchor Ledger

Record a salary contribution into the Cash Anchor dividend pool:

```text
/contribute 5000
/contribute 5000 2026-05-24 A股红利池月度工资投入
```

Aliases:

```text
/salary 5000
/deposit 5000
```

The agent appends the record to:

```text
frameworks/Cash_Anchor/data/capital_flows.csv
```

It then replies with:

- current-year contribution total
- annual contribution target
- completion percentage
- remaining contribution gap

Update the annual salary contribution target:

```text
/plan contribution=60000
```

Alias:

```text
/target contribution=50000
```

The agent updates:

```text
frameworks/Cash_Anchor/data/dividend_plan.yaml
```

新增或更新红利持仓。只需要填股票、股数、成本价；最新价后续由 Agent 查询：

```text
/holding 600900.SH 1000 24.5
```

批量写入：

```text
/holdings
600900.SH 长江电力 1000 24.5
601088.SH 中国神华 500 31.2
600036.SH 招商银行 800 34.5
```

Alias:

```text
/position 600900.SH 1000 24.5
```

Required fields:

- `symbol`: stock or ETF code
- `shares`: position size
- `cost`: cost price

Position format also supports an optional stock name:

```text
600900.SH 长江电力 1000 24.5
```

Optional fields:

- `name`
- `market`
- `currency`
- `current`: current price; normally omitted for A-share dividend holdings
- `dividend`: annual dividend per share; if omitted, dividend capacity is marked as pending estimate
- `tax`
- `notes`

The agent updates:

```text
frameworks/Cash_Anchor/data/holdings.csv
```

Agent 会返回当前预估年分红能力、成本股息率和年度投入进度。系统不再设置目标年分红；年复盘时评估实际分红、收益率和框架执行质量。

券商持仓 API 不可用时，用本地账本记录低频持仓事件：

```text
/buy symbol=600000 shares=1000 price=8.52 date=2026-05-25 name=示例银行 dividend=0.4
/sell symbol=600000 shares=500 price=9.10 date=2026-05-25
/dividend symbol=600000 amount=320.50 date=2026-06-20
/snapshot
```

对于 A 股持仓，Agent 以本地账本为准。券商 API 只作为可用时的同步或对账来源。

本地持仓事件保存位置：

```text
frameworks/Cash_Anchor/data/portfolio_events.csv
```

### Growth Engine 复盘

批量新增或更新 Growth_Engine 持仓，每行一只股票：

```text
/growth-holdings
symbol=300750.SZ name=宁德时代 market=CN shares=100 cost=180 current=195 type=核心仓 thesis=动力电池龙头
symbol=688256.SH name=寒武纪 market=CN shares=50 cost=600 current=650 type=试错仓 thesis=国产AI芯片
```

批量新增或更新 Growth_Engine 自选股：

```text
/growth-watchlist
symbol=300750.SZ name=宁德时代 market=CN priority=high reason=新能源龙头 trigger=利润重新加速
symbol=688981.SH name=中芯国际 market=CN priority=medium reason=国产半导体 trigger=毛利率企稳
```

按需复盘单只 Growth_Engine 标的：

```text
/growth-review NVDA.US
```

查看本地 Growth_Engine 持仓和自选股快照：

```text
/growth-snapshot
/growth-snapshot market=US
```

运行市场定时复盘脚本：

```bash
python3 scripts/run_growth_daily_review.py --market CN
python3 scripts/run_growth_daily_review.py --market US --chat-id <feishu_chat_id>
```

如果 `.env` 中配置了 `FEISHU_DEFAULT_CHAT_ID`，脚本会默认把复盘结果推送到该会话。命令行 `--chat-id` 优先级更高，可临时覆盖默认会话。

查看 Scheduler 配置：

```bash
python3 scripts/run_scheduler.py --list
```

干跑单个定时任务，不调用 LLM，不推送飞书：

```bash
python3 scripts/run_scheduler.py --run-once growth_cn_daily_review
python3 scripts/run_scheduler.py --run-once growth_us_daily_review
python3 scripts/run_scheduler.py --run-once growth_weekly_review
```

真实执行单个定时任务需要显式加 `--execute`：

```bash
python3 scripts/run_scheduler.py --run-once growth_cn_daily_review --execute
```

常驻 Scheduler 入口：

```bash
python3 scripts/run_scheduler.py --run-loop
```

第一阶段采用本机常驻。目前已开启一周试用：`scheduler.enabled=true`，`dry_run_by_default=false`。启动 `python3 scripts/run_scheduler.py --run-loop` 后，到点会真实调用 LLM，并通过 `FEISHU_DEFAULT_CHAT_ID` 推送飞书。当前配置为 A 股每日 16:30、美股每日 06:00、周日 20:00 周复盘；每日任务跳过周末，节假日通过 `scheduler.holidays.CN/US` 手工维护。

Growth_Engine 本地文件：

```text
frameworks/Growth_Engine/data/growth_holdings.csv
frameworks/Growth_Engine/data/growth_watchlist.csv
```

当前版本使用本地持仓、自选股、本地 `current_price`、Growth_Engine 宪法和只读市场数据 Provider。复盘前会按市场补充行情上下文：A 股走 Yahoo Finance / yfinance，美股走 Longbridge。新闻、公告和财报数据暂未自动接入。

长桥美股持仓同步按只读 Provider 实现：

```text
/sync longbridge
/apply longbridge cash_anchor
```

当前状态：Provider 可以生成同步提案，并在明确命令确认后写入 Cash Anchor 子集。A 股持仓仍以手工本地账本为主。

长桥同步通过固定 Python Provider 实现，只运行固定的只读白名单命令：

```text
longbridge positions --format json
longbridge quote <Cash Anchor symbols> --format json
```

对 Cash Anchor，Provider 只保留：

```text
QQQI, XQQI, TQQQ
```

其他长桥持仓会被过滤，避免成长股进入现金流账本。

复核同步提案后再使用 `/apply longbridge cash_anchor`。该命令会重新读取长桥持仓和报价，只把 QQQI/XQQI/TQQQ 写入 Cash Anchor 账本，用报价刷新当前价，并保留已有的分红和税率字段。

外部命令边界：

- LLM 代码不直接调用 shell 命令。
- 券商工具只通过固定 Python 函数暴露。
- 长桥 CLI 使用固定参数数组调用，不拼接 shell 字符串。
- 不开放下单、改单、撤单等交易命令。

Local Cash Anchor data files:

```text
frameworks/Cash_Anchor/data/holdings.csv
frameworks/Cash_Anchor/data/capital_flows.csv
frameworks/Cash_Anchor/data/portfolio_events.csv
frameworks/Cash_Anchor/data/dividend_plan.yaml
```

Skill payload contract:

```text
{
  "skill_id": "...",
  "description": "...",
  "path": "...",
  "arguments": {...},
  "tool_policy": {
    "risk_level": "low|medium|high",
    "access_type": "local_read|external_read|rule_write",
    "requires_human_approval": false
  },
  "result": {
    "status": "ok|error|missing|empty|provider_not_configured|unauthorized",
    "source": "local|yfinance|longbridge|iwencai_news_search|...",
    "data_type": "portfolio_snapshot|market_data|news|dossier|trade_history|...",
    "data": {...},
    "freshness": {
      "as_of": "2026-06-03T16:30:00",
      "stale": false,
      "stale_reason": ""
    },
    "warnings": [],
    "error": "..."
  }
}
```

All Skill disclosures are governed by `configs/tool_registry.yaml` and normalized by `src/skills.py` before they are shown to Worker or Auditor prompts.

### Knowledge Absorption

Generate a constitution patch proposal from fragmentary knowledge:

```text
/absorb Cash_Anchor 红利策略里，单纯高股息率不等于安全边际...
/absorb Cash_Anchor/CN_Dividend_Income 高股息必须同时检查分红覆盖率和自由现金流...
/absorb Cash_Anchor/US_Income_Options QQQI 和 XQQI 的分红复投需要区分基础份额和弹性仓位...
/absorb Growth_Engine/CN_Alpha_Growth 成长股买入必须同时满足基本面逻辑和趋势纪律...
```

Available absorption targets:

- `Cash_Anchor`: shared cash-flow framework.
- `Cash_Anchor/CN_Dividend_Income`: A-share dividend sub-framework.
- `Cash_Anchor/US_Income_Options`: US dollar income/options sub-framework.
- `Growth_Engine`: shared growth framework.
- `Growth_Engine/CN_Alpha_Growth`: A-share growth sub-framework.
- `Growth_Engine/US_Disruptive_Growth`: US growth sub-framework.

The normal workflow is:

1. Receive fragmentary knowledge.
2. Generate a structured patch proposal.
3. Run rules-change audit.
4. Ask for human review with three choices: discuss, accept, or reject.
5. If discussion is selected, normal Feishu messages are attached to that patch until the final decision. Each discussion turn calls the knowledge absorber LLM with the original proposal, target constitution, audit opinion, full patch discussion log, and the latest user message.
6. The final decision is only accept or reject. There is no observation-pool state.
7. Only write to constitution files after explicit approval.

Local proposal and inbox files are stored under:

```text
frameworks/*/knowledge_inbox/
frameworks/*/patch_proposals/
frameworks/*/patch_archive/
```

### Info Commands

```text
/status
/usage
/frameworks
```

Generate a token report:

```bash
python3 scripts/token_report.py --date 2026-05-17 --top 10
```

## Privacy Boundary

The following are local-only and ignored by Git:

- `.env`
- `frameworks/*/logs/*`
- `frameworks/*/chat_history/*`
- `frameworks/*/data/*`
- `frameworks/*/knowledge_inbox/*`
- `frameworks/*/patch_proposals/*`
- `frameworks/*/patch_archive/*`
- `frameworks/*/research_dossiers/*`
- `runtime/token_usage/*`
- Python cache files

This lets the public repository show the engineering design without exposing private investment records.

## Disclaimer

This is an engineering project and personal AI assistant framework. It is not financial advice and should not be used as an automated trading system without independent review and risk controls.
