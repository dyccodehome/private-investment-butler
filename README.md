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
- **OpenAI Responses API**: default model is configurable as `gpt-5.5`.

## Architecture

```text
private_investment_butler/
├── AGENTS.md                     # Agent framework document
├── config.yaml                   # Non-secret runtime config
├── main.py                       # Pipeline entry
├── frameworks/                   # Strategy islands
│   ├── Cash_Anchor/
│   └── Growth_Engine/
├── skills/                       # On-demand Skill instructions and tools
├── src/                          # Core orchestration modules
├── scripts/                      # Local reports and utilities
└── runtime/                      # Local-only runtime ledgers
```

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
7. Local black-box logging by `src/context_logger.py`
8. Token usage logging by `src/token_monitor.py`

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
python3 -m src.feishu_long_connection
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

Update the annual contribution target or target annual dividend:

```text
/plan contribution=50000 dividend=115000
/plan contribution=60000
/plan dividend=120000
```

Alias:

```text
/target contribution=50000
```

The agent updates:

```text
frameworks/Cash_Anchor/data/dividend_plan.yaml
```

Add or update a holding and recalculate dividend capacity:

```text
/holding symbol=600000 name=示例银行 shares=1000 cost=10 current=10.5 dividend=0.4 tax=0
```

Alias:

```text
/position symbol=600000 shares=1000 cost=10 current=10.5 dividend=0.4
```

Required fields:

- `symbol`: stock or ETF code
- `shares`: position size
- `cost`: cost price
- `current`: current price
- `dividend`: annual dividend per share

Optional fields:

- `name`
- `market`
- `currency`
- `tax`
- `notes`

The agent updates:

```text
frameworks/Cash_Anchor/data/holdings.csv
```

It then replies with current estimated annual dividend capacity and the remaining dividend target gap.

Record low-frequency portfolio events when broker position API is unavailable:

```text
/buy symbol=600000 shares=1000 price=8.52 date=2026-05-25 name=示例银行 dividend=0.4
/sell symbol=600000 shares=500 price=9.10 date=2026-05-25
/dividend symbol=600000 amount=320.50 date=2026-06-20
/snapshot
```

The agent treats the local ledger as the source of truth for A-share positions. Broker APIs are used only as sync or reconciliation sources when available.

Local portfolio events are stored in:

```text
frameworks/Cash_Anchor/data/portfolio_events.csv
```

Longbridge US position sync is implemented as a read-only provider:

```text
/sync longbridge
/apply longbridge cash_anchor
```

Current status: the provider can generate a sync proposal and apply the Cash Anchor subset after explicit command confirmation. A-share positions remain manual-ledger first.

Longbridge sync is implemented through a fixed Python provider. It only runs the read-only whitelist command:

```text
longbridge positions --format json
```

For Cash Anchor, the provider keeps only:

```text
QQQI, XQQI, TQQQ
```

Other Longbridge holdings are filtered out so growth positions do not enter the cash-flow ledger.

Use `/apply longbridge cash_anchor` after reviewing the proposal. The apply command re-reads Longbridge positions, writes only QQQI/XQQI/TQQQ into the Cash Anchor ledger, and preserves existing current price, dividend, and tax fields where present.

External command boundary:

- LLM code never calls shell commands directly.
- Broker tools are exposed only through fixed Python functions.
- Longbridge CLI is invoked with a fixed argument array, not a shell string.
- Trading commands such as order submit, replace, and cancel are not exposed.

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
  "result": {
    "status": "ok|error",
    "data": {...},
    "source": "...",
    "error": "..."
  }
}
```

Current deterministic local skills may return the raw snapshot object as `result`; new skills should use the structured `status/data/source/error` shape.

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
4. Ask for human review.
5. Only write to constitution files after explicit approval.

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
