# Private Investment Butler

> 本地优先、纯 Python 编排的私人投资管家多智能体系统。它面向 A 股和美股投资研究，把策略隔离、工具治理、行情 fallback、新闻/公告情报、输出契约、独立审计、飞书交互和本地复盘记录组合成一套可审计的投资 Agent Runtime。

[功能特性](#功能特性) · [系统架构](#系统架构) · [快速开始](#快速开始) · [定时工作流](#定时工作流) · [常用命令](#常用命令) · [复盘与观测](#复盘与观测) · [English](README.md)

这个项目不是交易机器人。它的目标是让私人投资事实尽量留在本地，让模型看到的每一份事实都有来源、有质量摘要、有权限边界，并且禁止 LLM 直接控制券商工具或绕过人工审批修改策略规则。

## 当前范围

| 模块 | 当前设计 |
| --- | --- |
| 市场范围 | 只专注 A 股和美股。港股暂不纳入当前维护范围。 |
| 运行方式 | 本地优先，核心生命周期由 `main.py` 显式控制；不引入 LangGraph 等重型状态机框架。 |
| 通讯入口 | 飞书长连接接收消息和审批卡片；CLI 用于本地测试。 |
| 策略岛 | `Cash_Anchor` 负责现金流、防守仓、分红、期权收益和流动性；`Growth_Engine` 只负责长桥来源的美股颠覆性成长。 |
| 数据接入 | 通过 `configs/tool_registry.yaml` 治理 Skill 披露；LLM 不允许自由调用 shell。 |
| 交易边界 | 不开放下单、改单、撤单。券商相关能力只读、固定函数、固定命令参数。 |
| WebUI | 当前不做通用 WebUI。系统保留本地 trace、成本和复盘统计接口。 |

## 功能特性

| 能力 | 说明 |
| --- | --- |
| 策略隔离 Agent | Master Router 每次只把问题路由到一个策略岛；Worker 只读取本策略 `constitution.md` 和必要子框架。 |
| 渐进披露 | Worker 先申请 `SkillRequest`，主管道按 Tool Registry 审批后才披露数据。 |
| 工具治理 | `configs/tool_registry.yaml` 记录允许框架、允许 Agent、风险等级、访问类型、超时、输出 schema 和是否需要人工审批。 |
| 行情数据源 fallback | A 股行情走 `yfinance`；美股行情优先 Longbridge，失败后 fallback 到 `yfinance`，并记录 `source_chain`。 |
| 市场阶段上下文 | 行情 payload 附带 A 股/美股市场阶段、本地市场时间、是否交易日、是否盘中、是否部分 K 线等上下文。 |
| 新闻/公告情报 | 识别到具体标的后可申请新闻；涉及财报、分红、交易动作或风险时追加公告检索。没有配置 Provider 时会标记为数据缺口，不编造事实。 |
| 数据质量摘要 | 每个标准 Skill payload 都带 `data_quality`，记录覆盖度、鲜度、来源链和限制。 |
| 输出契约 | 子 Agent 草案会检查是否覆盖结论、关键事实、风险或限制、下一步动作。缺失项会进入审计和复盘。 |
| 历史判断快照 | 本地交易历史和研究档案会压缩进本轮 `decision_snapshot`，便于后续比较新旧判断。 |
| 独立审计关 | Auditor 是单独 LLM 调用，会按场景选择风险审计、规则变更审计或流程审计，并可触发熔断。 |
| 人工熔断 | 审计拒绝时不会直接输出给用户，而是通过飞书审批卡片等待继续或放弃。 |
| Decision Record | 每次终态决策写入 `runtime/decisions/YYYY-MM-DD.jsonl`，包含披露数据、审计信号、输出契约和数据质量。 |
| 定时工作流 | `config.yaml` 配置每日/每周复盘任务，由 `scripts/run_scheduler.py` 执行。 |
| Token 与 Trace | 每次 LLM 调用写入 token usage、估算成本、trace 事件、风险标签和 prompt fingerprint。 |
| 知识吸收 | `/absorb` 把外部片段转成宪法补丁提案，经过审计和人工确认后才写入规则。 |

## 系统架构

```text
用户消息或 CLI 输入
  -> main.py::run_pipeline
  -> Master Router
  -> 唯一策略岛
     -> Worker 接单预检
     -> Skill 申请
     -> 受治理的数据披露
     -> Worker 生成草案
  -> 输出契约与决策快照
  -> Auditor 独立审计
  -> 熔断判断
  -> communication_gate 输出
  -> Decision Record、Trace、Token Usage、Chat History
```

核心目录：

```text
private_investment_butler/
├── main.py                         # CLI 入口和显式管道控制
├── config.yaml                     # 非密钥模型、定时任务、预算和成本配置
├── configs/tool_registry.yaml      # Tool Registry 治理配置
├── frameworks/
│   ├── Cash_Anchor/
│   │   ├── constitution.md
│   │   └── sub_frameworks/
│   └── Growth_Engine/
│       ├── constitution.md
│       └── sub_frameworks/
├── prompts/                        # System/User prompt 模板
├── skills/                         # 按需加载的 Skill 和工具边界
├── src/
│   ├── market_data/                # 行情 Provider 和 fallback router
│   ├── scheduler/                  # 定时复盘 runner
│   ├── state.py                    # AgentState，全局唯一事实来源
│   ├── sub_agent.py                # Worker 预检、上下文选择和 Skill 申请
│   ├── skills.py                   # Skill 加载和标准 payload envelope
│   ├── auditor.py                  # 独立审计关
│   ├── output_contract.py          # 输出契约与决策快照
│   ├── data_quality.py             # 披露数据质量摘要
│   ├── decision_record.py          # 本地终态决策记录
│   └── knowledge_absorber.py       # 宪法补丁提案
├── scripts/
│   ├── run_scheduler.py
│   ├── decision_review_report.py
│   └── token_report.py
└── runtime/                        # 本地 trace、决策记录、scheduler 状态和 token usage
```

## 策略岛

| 策略 | 子框架 | 角色 |
| --- | --- | --- |
| `Cash_Anchor` | `CN_Dividend_Income`, `US_Income_Options` | 防守端现金流锚点。维护 A 股红利现金流、美股收益资产、期权纪律、流动性和本地账本。 |
| `Growth_Engine` | `US_Disruptive_Growth` | 进攻端美股成长引擎。标的来自长桥持仓和自选，经现金流标的、期权、杠杆 ETF、指数过滤后进入 universe。 |

每个策略岛维护自己的本地私有状态：

```text
frameworks/{strategy}/data/
frameworks/{strategy}/chat_history/
frameworks/{strategy}/research_dossiers/
frameworks/{strategy}/knowledge_inbox/
frameworks/{strategy}/patch_proposals/
frameworks/{strategy}/patch_archive/
```

仓库只应提交公开安全的脚手架和模板。真实账本、聊天记录、研究档案、运行 trace 和密钥都应保留在本地。

## 数据契约

所有可执行 Skill 在披露给 Worker 或 Auditor 前，都会被标准化：

```json
{
  "status": "ok | error | missing | empty | provider_not_configured | unauthorized",
  "source": "local | yfinance | longbridge | market_intel_news | market_intel_announcements | ...",
  "data_type": "portfolio_snapshot | market_data | news | announcement | research_dossier | trade_history",
  "data": {},
  "freshness": {
    "as_of": "2026-06-04T16:30:00",
    "stale": false,
    "stale_reason": ""
  },
  "warnings": [],
  "error": "",
  "source_chain": [
    {"provider": "longbridge", "status": "error", "error": "not configured"},
    {"provider": "yfinance", "status": "ok", "error": ""}
  ],
  "data_quality": {
    "coverage": {"quote": "ok", "dividend": "missing", "market_phase": "ok"},
    "freshness": "fresh",
    "limitations": ["行情源股息字段不能作为现金流事实。"]
  }
}
```

输出也有本地契约：

```text
最小输出 = 结论 + 关键事实 + 风险或限制 + 下一步动作
```

检查结果会写入决策快照，后续复盘统计可以直接读取。

## 快速开始

安装依赖：

```bash
python3 -m pip install -r requirements.txt
```

创建本地环境变量：

```bash
cp .env.example .env
```

常用变量：

| 变量 | 用途 |
| --- | --- |
| `DEEPSEEK_API_KEY` | 默认模型 Provider Key。 |
| `OPENAI_API_KEY` | 可选 OpenAI Responses API Provider。 |
| `GEMINI_API_KEY` | 可选 Gemini Provider。 |
| `FEISHU_APP_ID`, `FEISHU_APP_SECRET` | 飞书长连接应用凭据。 |
| `FEISHU_VERIFICATION_TOKEN`, `FEISHU_ENCRYPT_KEY` | 飞书事件校验配置。 |
| `FEISHU_DEFAULT_CHAT_ID` | 定时任务默认推送会话。 |
| `YUQUE_TOKEN`, `YUQUE_NAMESPACE`, `YUQUE_ARCHIVE_DIR` | 可选知识归档集成。 |

运行本地检查：

```bash
python3 -m unittest discover
python3 -m compileall .
```

用 CLI 跑一个问题：

```bash
printf 'NVDA 要不要加仓\n' | python3 main.py
```

启动飞书长连接：

```bash
python3 -m src.feishu_long_connection
```

飞书路径使用 SDK 长连接，不需要公网回调地址。

## 定时工作流

定时任务配置位于 `config.yaml::scheduler.jobs`。

| 任务 | 市场 | 时间 | 用途 |
| --- | --- | --- | --- |
| `cash_anchor_cn_premarket_review` | CN | 工作日 08:50 Asia/Shanghai | A 股红利开盘计划。 |
| `cash_anchor_cn_close_review` | CN | 工作日 16:20 Asia/Shanghai | A 股红利收盘复盘。 |
| `cash_anchor_us_premarket_review` | US | 工作日 08:30 America/New_York | 美股现金流开盘计划。 |
| `growth_us_premarket_review` | US | 工作日 08:40 America/New_York | 美股成长开盘计划。 |
| `cash_anchor_us_close_review` | US | 工作日 17:10 America/New_York | 美股现金流收盘复盘。 |
| `growth_us_close_review` | US | 工作日 17:20 America/New_York | 美股成长收盘复盘。 |
| `cash_anchor_weekly_review` | ALL | 周日 20:00 Asia/Shanghai | 现金锚点周复盘。 |
| `growth_weekly_review` | ALL | 周日 20:10 Asia/Shanghai | 美股成长周复盘。 |

查看配置：

```bash
python3 scripts/run_scheduler.py --list
```

干跑单个任务：

```bash
python3 scripts/run_scheduler.py --run-once cash_anchor_cn_dividend_review
```

真实执行单个任务：

```bash
python3 scripts/run_scheduler.py --run-once growth_us_close_review --execute
```

启动常驻 Scheduler：

```bash
python3 scripts/run_scheduler.py --run-loop
```

## 常用命令

命令可通过 CLI 输入，也可通过飞书消息发送。

| 命令 | 用途 |
| --- | --- |
| `/help` | 查看可用命令。 |
| `/status` | 查看本地运行状态。 |
| `/usage` | 查看 token 和用量摘要。 |
| `/frameworks` | 查看策略框架。 |
| `/contribute 5000` | 记录 Cash Anchor 工资投入。 |
| `/plan contribution=60000` | 修改年度投入目标。 |
| `/holding 600900.SH 1000 24.5` | 新增或更新单只红利持仓。 |
| `/holdings` | 批量更新红利持仓。 |
| `/buy`, `/sell`, `/dividend`, `/snapshot` | 维护 Cash Anchor 本地事件和快照。 |
| `/sync longbridge` | 生成长桥只读同步提案。 |
| `/apply longbridge cash_anchor` | 确认后应用 Cash Anchor 子集同步。 |
| `/growth-universe` | 查看长桥归一化后的 Growth Engine universe。 |
| `/sync longbridge growth` | 读取长桥并生成 Growth Engine universe。 |
| `/growth-review NVDA.US` | 复盘单只 Growth Engine 标的。 |
| `/growth-snapshot` | 查看 Growth Engine 本地持仓和自选。 |
| `/absorb <target> <text>` | 生成经过审计的宪法补丁提案。 |

外部命令边界：

- LLM 不直接调用 shell。
- 券商能力只通过固定 Python 函数暴露。
- Longbridge 命令使用固定参数数组，且只读。
- 不开放下单、改单、撤单命令。

## 复盘与观测

Token 报告：

```bash
python3 scripts/token_report.py --date 2026-06-04 --top 10
```

决策复盘和回测样本统计：

```bash
python3 scripts/decision_review_report.py --date 2026-06-04
python3 scripts/decision_review_report.py --start-date 2026-06-01 --end-date 2026-06-04 --json
```

Decision Record 保存位置：

```text
runtime/decisions/YYYY-MM-DD.jsonl
```

Trace 和 Token 日志保存位置：

```text
runtime/traces/YYYY-MM-DD.jsonl
runtime/token_usage/YYYY-MM-DD.jsonl
```

## 隐私边界

以下内容应保持本地化：

- `.env`
- `frameworks/*/data/*`
- `frameworks/*/chat_history/*`
- `frameworks/*/research_dossiers/*`
- `frameworks/*/knowledge_inbox/*`
- `frameworks/*/patch_proposals/*`
- `frameworks/*/patch_archive/*`
- `runtime/*`
- Python cache files

仓库应展示架构、模板和公开安全的工程实现，不暴露私人投资记录。

## 免责声明

本项目是个人投资研究和工作流治理的工程框架，不构成投资建议，不是荐股系统，也不是自动交易系统。任何投资动作都需要独立判断、仓位管理和风险控制。
